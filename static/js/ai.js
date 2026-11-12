/*
 * 폴리마켓 AI 도우미 (vanilla, 의존: app.js 의 window.Poly · htmx 선택)
 * - 상품 폼 AI 패널: #id_images 앞 2장을 줄여서 FormData 로 ai:describe / ai:recognize 호출
 * - 결과 카드의 [data-ai-apply] 를 눌러야 폼 필드가 바뀌어요 (자동 덮어쓰기 금지, 기존 값이 있으면 확인)
 * - 협상 답장 초안 [data-ai-fill] → 채팅 입력창에 채우기
 * - [data-ai-dismiss] → 결과/오류 카드 닫기
 * 여러 번 로드돼도(HTMX 조각의 <script>) 한 번만 초기화해요.
 */
(function () {
  "use strict";
  if (window.PolyAI) return;

  var MAX_IMAGES = 2;
  var MAX_SIDE = 1280;
  var REQUEST_TIMEOUT_MS = 45000;
  var busy = false;

  /* ───────── 유틸 ───────── */
  function toast(message, level) {
    if (window.Poly && window.Poly.toast) window.Poly.toast(message, level || "info");
  }
  function csrfToken() {
    var field = document.querySelector("input[name=csrfmiddlewaretoken]");
    if (field) return field.value;
    try { return JSON.parse(document.body.getAttribute("hx-headers") || "{}")["X-CSRFToken"] || ""; } catch (e) { return ""; }
  }
  function byId(id) { return document.getElementById(id); }

  // 오류 카드 (서버 응답을 못 받았을 때). 사용자 데이터 없음 → 고정 문구만
  function errorCard(title, message) {
    var box = document.createElement("div");
    box.className = "alert alert-warning";
    box.setAttribute("role", "alert");
    box.setAttribute("data-ai-error", "");
    var body = document.createElement("div");
    body.className = "min-w-0 flex-1";
    var t = document.createElement("p");
    t.className = "alert-title";
    t.textContent = title;
    var m = document.createElement("p");
    m.textContent = message;
    body.appendChild(t);
    body.appendChild(m);
    box.appendChild(body);
    return box;
  }

  function setField(el, value) {
    if (!el) return false;
    el.value = value;
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
    el.classList.remove("ai-applied");
    void el.offsetWidth; // 애니메이션 재시작
    el.classList.add("ai-applied");
    setTimeout(function () { el.classList.remove("ai-applied"); }, 1600);
    return true;
  }

  // 기존 값이 있고 다르면 덮어쓸지 묻기
  function canOverwrite(fields, label) {
    var dirty = fields.some(function (pair) {
      return pair[0] && pair[0].value.trim() !== "" && pair[0].value.trim() !== String(pair[1]).trim();
    });
    return !dirty || window.confirm("이미 입력한 " + label + "을(를) AI 결과로 바꿀까요?");
  }

  function readJson(card) {
    var id = card && card.getAttribute("data-ai-json");
    var node = id ? byId(id) : null;
    if (!node) return null;
    try { return JSON.parse(node.textContent); } catch (e) { return null; }
  }

  /* ───────── 이미지 줄이기 (실패하면 원본 그대로) ───────── */
  function loadImage(file) {
    return new Promise(function (resolve, reject) {
      var url = URL.createObjectURL(file);
      var img = new Image();
      img.onload = function () { URL.revokeObjectURL(url); resolve(img); };
      img.onerror = function () { URL.revokeObjectURL(url); reject(new Error("load")); };
      img.src = url;
    });
  }
  function shrink(file) {
    if (!/^image\/(jpeg|png|webp)$/.test(file.type)) return Promise.resolve(file);
    return loadImage(file).then(function (img) {
      var scale = Math.min(1, MAX_SIDE / Math.max(img.naturalWidth, img.naturalHeight));
      if (scale === 1 && file.size < 1024 * 1024) return file;
      var canvas = document.createElement("canvas");
      canvas.width = Math.round(img.naturalWidth * scale);
      canvas.height = Math.round(img.naturalHeight * scale);
      var ctx = canvas.getContext("2d");
      ctx.fillStyle = "#fff";
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
      return new Promise(function (resolve) {
        canvas.toBlob(function (blob) {
          resolve(blob ? new File([blob], (file.name || "photo").replace(/\.\w+$/, "") + ".jpg", { type: "image/jpeg" }) : file);
        }, "image/jpeg", 0.85);
      });
    }).catch(function () { return file; });
  }

  function selectedImages() {
    var input = byId("id_images");
    var files = input && input.files ? Array.prototype.slice.call(input.files) : [];
    return files.filter(function (f) { return /^image\//.test(f.type); }).slice(0, MAX_IMAGES);
  }

  /* ───────── 상품 폼: describe / recognize ───────── */
  function setBusy(panel, state) {
    busy = state;
    panel.setAttribute("aria-busy", state ? "true" : "false");
    Array.prototype.forEach.call(panel.querySelectorAll("[data-ai-action]"), function (btn) { btn.disabled = state; });
  }

  function showLoading(result, text) {
    var tpl = byId("ai-loading-template");
    result.innerHTML = "";
    if (tpl) {
      var frag = tpl.content.cloneNode(true);
      var label = frag.querySelector("[data-ai-loading-text]");
      if (label) label.textContent = text;
      result.appendChild(frag);
    }
  }

  function runPanelAction(button) {
    var panel = button.closest("[data-ai-panel]") || document.querySelector("[data-ai-panel]");
    if (!panel || busy) return;
    var action = button.getAttribute("data-ai-action");
    var url = panel.getAttribute(action === "recognize" ? "data-recognize-url" : "data-describe-url");
    var result = byId("ai-result");
    var keywordsEl = panel.querySelector("[data-ai-keywords]");
    var keywords = keywordsEl ? keywordsEl.value.trim() : "";
    var files = selectedImages();

    if (action === "recognize" && !files.length) {
      result.replaceChildren(errorCard("사진이 필요해요", "위에서 상품 사진을 먼저 추가해 주세요."));
      return;
    }
    if (action === "describe" && !files.length && !keywords) {
      result.replaceChildren(errorCard("사진이나 키워드가 필요해요", "사진을 추가하거나 키워드를 입력해 주세요."));
      if (keywordsEl) keywordsEl.focus();
      return;
    }

    setBusy(panel, true);
    showLoading(result, action === "recognize" ? "사진을 살펴보는 중이에요" : "AI가 작성 중이에요");

    Promise.all(files.map(shrink)).then(function (images) {
      var data = new FormData();
      images.forEach(function (f) { data.append("images", f, f.name || "photo.jpg"); });
      data.append("keywords", keywords);
      var category = byId("id_category");
      if (category && category.value) data.append("category", category.value);
      if (button.hasAttribute("data-ai-regenerate")) data.append("regenerate", "1");

      var controller = window.AbortController ? new AbortController() : null;
      var timer = controller ? setTimeout(function () { controller.abort(); }, REQUEST_TIMEOUT_MS) : null;
      return fetch(url, {
        method: "POST",
        body: data,
        credentials: "same-origin",
        headers: { "X-CSRFToken": csrfToken() },
        signal: controller ? controller.signal : undefined,
      }).then(function (res) {
        if (timer) clearTimeout(timer);
        if (res.redirected) throw new Error("login");
        return res.text();
      });
    }).then(function (html) {
      result.innerHTML = html; // 서버가 이스케이프한 조각
      if (window.htmx) window.htmx.process(result);
      var card = result.firstElementChild;
      if (card && card.scrollIntoView) card.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }).catch(function (err) {
      var msg = err && err.message === "login" ? "로그인이 풀렸어요. 다시 로그인해 주세요."
        : err && err.name === "AbortError" ? "AI 응답이 늦어지고 있어요. 잠시 후 다시 시도해 주세요."
        : "네트워크 연결을 확인하고 다시 시도해 주세요.";
      result.replaceChildren(errorCard("AI 도우미를 부르지 못했어요", msg));
    }).then(function () {
      setBusy(panel, false);
    });
  }

  /* ───────── 적용 버튼 ───────── */
  function applyResult(button) {
    var card = button.closest("[data-ai-result]");
    var data = readJson(card);
    if (!data) return;
    var kind = button.getAttribute("data-ai-apply");
    var title = byId("id_title");
    var content = byId("id_content");

    if (kind === "description") {
      var body = data.content || "";
      var withTags = card.querySelector("[data-ai-with-tags]");
      if (withTags && withTags.checked && data.suggested_tags && data.suggested_tags.length) {
        body += "\n\n" + data.suggested_tags.map(function (t) { return "#" + t; }).join(" ");
      }
      if (!canOverwrite([[title, data.title], [content, body]], "제목과 설명")) return;
      setField(title, data.title);
      setField(content, body);
      toast("초안을 적용했어요. [대괄호] 부분을 채워 주세요.", "success");
      if (content) content.focus({ preventScroll: false });
    } else if (kind === "title" || kind === "vision-title") {
      if (!data.title || !canOverwrite([[title, data.title]], "제목")) return;
      setField(title, data.title);
      toast("제목을 적용했어요.", "success");
    } else if (kind === "recognize") {
      var category = byId("id_category");
      var condition = byId("id_condition");
      var applied = [];
      if (category && data.category_id && category.querySelector('option[value="' + Number(data.category_id) + '"]')) {
        setField(category, String(data.category_id));
        applied.push("카테고리");
      }
      if (condition && data.condition && condition.querySelector('option[value="' + String(data.condition).replace(/[^A-Z_]/g, "") + '"]')) {
        setField(condition, data.condition);
        applied.push("상품 상태");
      }
      toast(applied.length ? applied.join("·") + "를 적용했어요." : "적용할 항목을 찾지 못했어요.", applied.length ? "success" : "warning");
    }
    button.setAttribute("aria-pressed", "true");
  }

  /* ───────── 협상 초안 → 채팅 입력창 ───────── */
  function fillDraft(button) {
    var target = document.querySelector(button.getAttribute("data-ai-fill"));
    if (!target) { toast("지금은 메시지를 보낼 수 없어요.", "warning"); return; }
    target.value = button.getAttribute("data-ai-text") || "";
    target.dispatchEvent(new Event("input", { bubbles: true }));
    target.focus();
    try { target.setSelectionRange(target.value.length, target.value.length); } catch (e) { /* 무시 */ }
    var list = button.closest("[data-ai-drafts]");
    if (list) {
      Array.prototype.forEach.call(list.querySelectorAll("[data-ai-fill]"), function (b) { b.setAttribute("aria-pressed", "false"); });
    }
    button.setAttribute("aria-pressed", "true");
  }

  /* ───────── 이벤트 위임 ───────── */
  document.addEventListener("click", function (e) {
    var el = e.target.closest("[data-ai-action], [data-ai-apply], [data-ai-fill], [data-ai-dismiss]");
    if (!el) return;
    if (el.hasAttribute("data-ai-action")) { e.preventDefault(); runPanelAction(el); }
    else if (el.hasAttribute("data-ai-apply")) { e.preventDefault(); applyResult(el); }
    else if (el.hasAttribute("data-ai-fill")) { e.preventDefault(); fillDraft(el); }
    else if (el.hasAttribute("data-ai-dismiss")) {
      e.preventDefault();
      var box = el.closest("[data-ai-result], [data-ai-error], [data-ai-drafts]");
      if (box) box.remove();
    }
  });

  // 키워드 입력창에서 Enter → 상품 폼 제출 대신 AI 작성
  document.addEventListener("keydown", function (e) {
    if (e.key !== "Enter" || !e.target.matches || !e.target.matches("[data-ai-keywords]") || e.isComposing) return;
    e.preventDefault();
    var btn = document.querySelector('[data-ai-panel] [data-ai-action="describe"]');
    if (btn) runPanelAction(btn);
  });

  window.PolyAI = { run: runPanelAction, apply: applyResult, fill: fillDraft };
})();
