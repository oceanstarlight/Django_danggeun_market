/*
 * 폴리마켓 채팅방 실시간 처리 (vanilla, 의존: app.js 의 window.Poly, htmx)
 * - WebSocket(/ws/chat/<id>/) 연결 · 자동 재연결 · 재연결 시 놓친 메시지 보충(?after=)
 * - 메시지 렌더링: 사용자 데이터는 모두 textContent 로만 넣어요 (innerHTML 금지)
 * - 읽음: 화면을 보고 있을 때만 서버에 read 전송, 상대가 읽으면 내 메시지에 '읽음'
 * - 판매자 화면: 구매자의 협상 메시지에 AI 답장 초안 버튼(<template>)을 붙이고 htmx.process
 * - WebSocket 이 없으면 fetch POST 로 보내기/읽음 처리 대체
 * 마크업은 templates/chat/partials/message.html 과 맞춰야 해요.
 */
(function () {
  "use strict";

  var root = document.getElementById("chat-root");
  if (!root) return;

  var ME = Number(root.dataset.userId);
  var SELLER_ID = Number(root.dataset.sellerId);
  var BUYER_ID = Number(root.dataset.buyerId);
  var WS_PATH = root.dataset.wsPath;
  var READ_URL = root.dataset.readUrl;
  var NEGOTIATE_URL = root.dataset.negotiateUrl || ""; // 예: /ai/negotiate/0/
  var CLOSE_CODES_FATAL = { 4401: "로그인이 필요해요.", 4403: "이 채팅방에 참여하고 있지 않아요.", 4404: "채팅방을 찾을 수 없어요." };

  var list = document.getElementById("chat-messages");
  var scroller = document.getElementById("chat-scroll");
  var form = document.getElementById("chat-form");
  var input = document.getElementById("chat-input");
  var conn = document.getElementById("chat-conn");
  var negoTpl = document.getElementById("chat-negotiation-template");
  var avatarTpl = document.getElementById("chat-partner-avatar");

  var socket = null;
  var retry = 0;
  var stopped = false;
  var pendingRead = false;
  var lastSent = "";
  var everConnected = false;

  var WEEKDAYS = ["일요일", "월요일", "화요일", "수요일", "목요일", "금요일", "토요일"];
  var ALERT_SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" class="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true"><path d="M10.3 4.2 2.4 17.8A2 2 0 0 0 4.1 20.8h15.8a2 2 0 0 0 1.7-3L13.7 4.2a2 2 0 0 0-3.4 0Z"/><path d="M12 9.5v4"/><path d="M12 17h.01"/></svg>';

  /* ───────── 유틸 ───────── */
  function toast(msg, level) { if (window.Poly) window.Poly.toast(msg, level); }
  function pad(n) { return (n < 10 ? "0" : "") + n; }
  // 서버(TIME_ZONE)와 같은 시간대로 날짜/시각을 표시 — 브라우저 시간대가 달라도 구분선이 어긋나지 않게
  var TZ = root.dataset.tz || undefined;
  var partsFmt = null;
  try {
    partsFmt = new Intl.DateTimeFormat("en-US", {
      timeZone: TZ, year: "numeric", month: "numeric", day: "numeric", weekday: "short",
      hour: "numeric", minute: "numeric", hourCycle: "h23",
    });
  } catch (e) { partsFmt = null; }
  var WD = { Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6 };
  function parts(d) {
    if (partsFmt && partsFmt.formatToParts) {
      var p = {};
      partsFmt.formatToParts(d).forEach(function (x) { p[x.type] = x.value; });
      return { y: +p.year, m: +p.month, d: +p.day, wd: WD[p.weekday], h: +p.hour % 24, min: +p.minute };
    }
    return { y: d.getFullYear(), m: d.getMonth() + 1, d: d.getDate(), wd: d.getDay(), h: d.getHours(), min: d.getMinutes() };
  }
  function dateKey(d) { var p = parts(d); return p.y + "-" + pad(p.m) + "-" + pad(p.d); }
  function dateLabel(d) { var p = parts(d); return p.y + "년 " + p.m + "월 " + p.d + "일 " + WEEKDAYS[p.wd]; }
  function timeLabel(d) {
    var p = parts(d);
    return (p.h < 12 ? "오전 " : "오후 ") + (p.h % 12 || 12) + ":" + pad(p.min);
  }
  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }
  function csrfToken() {
    var field = document.querySelector("input[name=csrfmiddlewaretoken]");
    if (field) return field.value;
    try { return JSON.parse(document.body.getAttribute("hx-headers") || "{}")["X-CSRFToken"] || ""; } catch (e) { return ""; }
  }
  function rows() { return list.querySelectorAll(".chat-row"); }
  function lastRow() { var r = rows(); return r.length ? r[r.length - 1] : null; }
  function lastMessageId() { var r = lastRow(); return r ? Number(r.dataset.messageId) : 0; }
  function lastDateKey() { var s = list.querySelectorAll("[data-date]"); return s.length ? s[s.length - 1].dataset.date : null; }
  function hasMessage(id) { return !!list.querySelector('.chat-row[data-message-id="' + Number(id) + '"]'); }

  function nearBottom() { return scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 160; }
  function scrollToBottom(smooth) {
    if (smooth && scroller.scrollTo) scroller.scrollTo({ top: scroller.scrollHeight, behavior: "smooth" });
    else scroller.scrollTop = scroller.scrollHeight;
  }

  // 같은 날짜 구분선이 두 번 생기면 앞의 것만 남긴다 (조각을 이어 붙일 때)
  function dedupeSeparators() {
    var seen = {};
    Array.prototype.forEach.call(list.querySelectorAll("[data-date]"), function (sep) {
      if (seen[sep.dataset.date]) sep.remove();
      else seen[sep.dataset.date] = true;
    });
  }

  function setConn(state) {
    if (!conn) return;
    conn.dataset.state = state;
    conn.textContent = state === "connecting" ? "연결 중" : state === "offline" ? "연결이 끊겼어요" : "";
  }

  /* ───────── 메시지 DOM ───────── */
  function negotiationButton(messageId) {
    if (!negoTpl || !NEGOTIATE_URL) return null;
    var frag = negoTpl.content.cloneNode(true);
    var realUrl = NEGOTIATE_URL.replace(/0\/?$/, String(Number(messageId)) + "/");
    // 템플릿 안 모든 속성에서 /ai/negotiate/0/ → 실제 id
    Array.prototype.forEach.call(frag.querySelectorAll("*"), function (node) {
      Array.prototype.forEach.call(node.attributes, function (attr) {
        if (attr.value.indexOf(NEGOTIATE_URL) !== -1) node.setAttribute(attr.name, attr.value.split(NEGOTIATE_URL).join(realUrl));
      });
    });
    return frag;
  }

  function buildMessage(msg) {
    var mine = Number(msg.sender_id) === ME;
    var created = new Date(msg.created_at);
    var frag = document.createDocumentFragment();

    var key = dateKey(created);
    var needSep = key !== lastDateKey();
    if (needSep) {
      var sep = el("div", "chat-date-sep");
      sep.dataset.date = key;
      sep.setAttribute("role", "separator");
      sep.appendChild(el("span", "", dateLabel(created)));
      frag.appendChild(sep);
    }

    var prev = lastRow();
    var first = !mine && (needSep || !prev || Number(prev.dataset.senderId) !== Number(msg.sender_id));

    var row = el("div", "chat-row is-new" + (mine ? " chat-row-me" : "") + (first ? " chat-row-first" : ""));
    row.dataset.messageId = String(Number(msg.id));
    row.dataset.senderId = String(Number(msg.sender_id));

    if (!mine) {
      var slot = el("div", "chat-avatar-slot");
      if (first && avatarTpl) slot.appendChild(avatarTpl.content.cloneNode(true));
      row.appendChild(slot);
    }

    var stack = el("div", "chat-stack");
    var line = el("div", "chat-line");
    line.appendChild(el("p", "bubble " + (mine ? "bubble-me" : "bubble-other"), msg.content));

    var meta = el("span", "chat-meta");
    if (mine) {
      var read = el("span", "chat-read", "읽음");
      read.setAttribute("data-read", "");
      read.hidden = !msg.is_read;
      meta.appendChild(read);
    }
    var time = el("time", "bubble-meta", timeLabel(created));
    time.setAttribute("datetime", msg.created_at);
    meta.appendChild(time);
    line.appendChild(meta);
    stack.appendChild(line);

    // 상대 메시지의 사기 의심 규칙 경고
    var warnings = Array.isArray(msg.fraud_warnings) ? msg.fraud_warnings : [];
    if (!mine && warnings.length) {
      var warn = el("div", "chat-warning");
      warn.setAttribute("role", "note");
      warn.insertAdjacentHTML("afterbegin", ALERT_SVG); // 고정 아이콘 (사용자 데이터 아님)
      var p = el("p");
      p.appendChild(el("strong", "font-semibold", "사기 의심 신호가 있어요."));
      p.appendChild(document.createTextNode(" " + warnings.map(String).join(" · ")));
      warn.appendChild(p);
      stack.appendChild(warn);
    }

    // 판매자 화면 + 구매자 협상 메시지 → AI 답장 초안 버튼
    if (!mine && ME === SELLER_ID && Number(msg.sender_id) === BUYER_ID && msg.is_negotiation) {
      var btn = negotiationButton(msg.id);
      if (btn) {
        var nego = el("div", "chat-nego");
        nego.appendChild(btn);
        var result = el("div", "chat-nego-result");
        result.setAttribute("aria-live", "polite");
        nego.appendChild(result);
        stack.appendChild(nego);
      }
    }

    row.appendChild(stack);
    frag.appendChild(row);
    return { frag: frag, row: row };
  }

  function removeEmpty() {
    var empty = document.getElementById("chat-empty");
    if (empty) empty.remove();
  }

  function appendMessage(msg) {
    if (!msg || msg.id == null || hasMessage(msg.id)) return;
    var mine = Number(msg.sender_id) === ME;
    var stick = mine || nearBottom();
    var built = buildMessage(msg);
    removeEmpty();
    list.appendChild(built.frag);
    if (window.htmx) window.htmx.process(built.row);
    if (stick) scrollToBottom(true);
    else if (!mine) toast("새 메시지가 왔어요", "info");
    if (!mine) requestRead();
  }

  // 서버가 렌더링한 조각(?after=)을 이어 붙인다 — 이미 있는 메시지는 건너뜀
  function appendFragmentHtml(html) {
    var box = document.createElement("div");
    box.innerHTML = html; // Django 템플릿이 이스케이프한 서버 HTML
    var older = box.querySelector("#chat-older");
    if (older) older.remove();
    Array.prototype.forEach.call(box.querySelectorAll(".chat-row"), function (row) {
      if (hasMessage(row.dataset.messageId)) {
        var prevSep = row.previousElementSibling;
        if (prevSep && prevSep.matches("[data-date]")) prevSep.remove();
        row.remove();
      }
    });
    if (!box.querySelector(".chat-row")) return;
    var stick = nearBottom();
    removeEmpty();
    var added = [];
    while (box.firstChild) { var n = box.firstChild; list.appendChild(n); if (n.nodeType === 1) added.push(n); }
    dedupeSeparators();
    if (window.htmx) added.forEach(function (n) { window.htmx.process(n); });
    if (stick) scrollToBottom(true);
  }

  function markRead(readerId, ids) {
    if (Number(readerId) === ME || !Array.isArray(ids)) return;
    ids.forEach(function (id) {
      var row = list.querySelector('.chat-row-me[data-message-id="' + Number(id) + '"]');
      var badge = row && row.querySelector("[data-read]");
      if (badge) badge.hidden = false;
    });
  }

  /* ───────── 읽음 요청 ───────── */
  function requestRead() {
    if (document.visibilityState !== "visible") { pendingRead = true; return; }
    pendingRead = false;
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: "read" }));
    } else if (READ_URL) {
      fetch(READ_URL, {
        method: "POST",
        headers: { "X-CSRFToken": csrfToken(), Accept: "application/json" },
        credentials: "same-origin",
      }).catch(function () { pendingRead = true; });
    }
  }
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "visible" && pendingRead) requestRead();
  });

  /* ───────── 놓친 메시지 보충 ───────── */
  function catchUp() {
    var url = window.location.pathname + "?after=" + lastMessageId();
    fetch(url, { headers: { "X-Chat-Fragment": "1" }, credentials: "same-origin" })
      .then(function (res) { return res.ok ? res.text() : ""; })
      .then(function (html) { if (html) appendFragmentHtml(html); })
      .catch(function () {});
  }

  /* ───────── WebSocket ───────── */
  function connect() {
    if (stopped || !WS_PATH || !("WebSocket" in window)) { setConn("offline"); return; }
    setConn("connecting");
    var proto = window.location.protocol === "https:" ? "wss://" : "ws://";
    try {
      socket = new WebSocket(proto + window.location.host + WS_PATH);
    } catch (e) {
      scheduleReconnect();
      return;
    }
    socket.onopen = function () {
      var reconnected = everConnected;
      everConnected = true;
      retry = 0;
      setConn("online");
      pendingRead = false; // 서버가 연결 시 읽음 처리
      if (reconnected) catchUp();
    };
    socket.onmessage = function (event) {
      var data;
      try { data = JSON.parse(event.data); } catch (e) { return; }
      if (data.type === "message") appendMessage(data.message);
      else if (data.type === "read") markRead(data.reader_id, data.message_ids);
      else if (data.type === "error") {
        toast(data.message || "메시지를 보내지 못했어요", "danger");
        if (input && !input.value && lastSent) { input.value = lastSent; input.dispatchEvent(new Event("input", { bubbles: true })); }
      }
    };
    socket.onclose = function (event) {
      socket = null;
      if (CLOSE_CODES_FATAL[event.code]) {
        stopped = true;
        setConn("offline");
        toast(CLOSE_CODES_FATAL[event.code], "danger");
        return;
      }
      scheduleReconnect();
    };
  }

  function scheduleReconnect() {
    if (stopped) return;
    setConn(retry > 0 ? "offline" : "connecting");
    var delay = Math.min(1000 * Math.pow(2, retry), 15000);
    retry += 1;
    setTimeout(connect, delay);
  }

  /* ───────── 보내기 ───────── */
  function sendViaHttp(text) {
    var body = new FormData();
    body.append("content", text);
    return fetch(form.action, {
      method: "POST",
      body: body,
      headers: { "X-CSRFToken": csrfToken(), Accept: "application/json" },
      credentials: "same-origin",
    })
      .then(function (res) { return res.json().catch(function () { return { ok: false }; }); })
      .then(function (data) {
        if (data.ok) appendMessage(data.message);
        else {
          toast(data.error || "메시지를 보내지 못했어요", "danger");
          if (!input.value) input.value = text;
        }
      })
      .catch(function () {
        toast("네트워크 연결을 확인해 주세요", "danger");
        if (!input.value) input.value = text;
      });
  }

  if (form && input) {
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var text = input.value.trim();
      if (!text) { input.focus(); return; }
      lastSent = text;
      input.value = "";
      input.dispatchEvent(new Event("input", { bubbles: true })); // 자동 높이 초기화
      input.focus();
      if (socket && socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: "message", content: text }));
      else sendViaHttp(text);
    });

    // 데스크톱: Enter 보내기 / Shift+Enter 줄바꿈 (한글 조합 중에는 무시). 터치 기기는 줄바꿈.
    var coarse = window.matchMedia && window.matchMedia("(pointer: coarse)").matches;
    input.addEventListener("keydown", function (e) {
      if (e.key !== "Enter" || e.shiftKey || e.isComposing || e.keyCode === 229 || coarse) return;
      e.preventDefault();
      if (form.requestSubmit) form.requestSubmit();
      else form.dispatchEvent(new Event("submit", { cancelable: true }));
    });
  }

  /* ───────── 이전 대화 불러오기 (HTMX) — 스크롤 위치 유지 ───────── */
  var olderAnchor = null;
  document.body.addEventListener("htmx:beforeRequest", function (e) {
    if (e.detail.elt && e.detail.elt.closest && e.detail.elt.closest("#chat-older")) {
      olderAnchor = { height: scroller.scrollHeight, top: scroller.scrollTop };
    }
  });
  document.body.addEventListener("htmx:afterSettle", function () {
    if (!olderAnchor) return;
    dedupeSeparators();
    scroller.scrollTop = scroller.scrollHeight - olderAnchor.height + olderAnchor.top;
    olderAnchor = null;
  });

  /* ───────── 시작 ───────── */
  scrollToBottom(false);
  if (window.location.hash === "#chat-bottom" && window.history.replaceState) {
    window.history.replaceState(null, "", window.location.pathname);
  }
  connect();
})();
