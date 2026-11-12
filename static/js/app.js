/*
 * 폴리마켓 공용 JS (vanilla, 의존성: htmx)
 * - 토스트: [data-toast] 3초 뒤 자동 닫힘, [data-toast-close], Poly.toast(msg, level), HX-Trigger "showToast"
 * - 드롭다운: [data-dropdown] > [data-dropdown-toggle] + [data-dropdown-menu]
 * - 토글: [data-toggle="#id"] → 대상 hidden 토글
 * - 모달: [data-modal-open="id"], [data-modal-close], ESC/오버레이 클릭, Poly.openModal/closeModal
 * - 이미지 미리보기: <input type="file" data-preview-target="#sel" [data-preview-max="10"]>
 * - 확인창: [data-confirm="정말 삭제할까요?"] (링크/버튼 클릭, 폼 제출)
 * - 텍스트영역 자동 높이: textarea[data-autoresize]
 * - HTMX: 요청 중 body.is-loading, 에러 토스트, 새로 들어온 콘텐츠 재초기화(htmx.onLoad)
 */
(function () {
  "use strict";

  var TOAST_TIMEOUT = 3000;
  var ICONS = {
    check: '<path d="m4.5 12.5 4.8 4.8L19.5 7"/>',
    alert: '<path d="M10.3 4.2 2.4 17.8A2 2 0 0 0 4.1 20.8h15.8a2 2 0 0 0 1.7-3L13.7 4.2a2 2 0 0 0-3.4 0Z"/><path d="M12 9.5v4"/><path d="M12 17h.01"/>',
    info: '<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5.5"/><path d="M12 7.8h.01"/>',
    x: '<path d="M18 6 6 18M6 6l12 12"/>',
  };

  function svg(name) {
    return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" class="h-5 w-5" aria-hidden="true">' + ICONS[name] + "</svg>";
  }

  function $(sel, root) { return (root || document).querySelector(sel); }
  function $all(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }

  /* ───────── 토스트 ───────── */
  function dismissToast(el) {
    if (!el || el.classList.contains("is-leaving")) return;
    el.classList.add("is-leaving");
    setTimeout(function () { el.remove(); }, 200);
  }

  function armToast(el) {
    if (el.dataset.toastArmed) return;
    el.dataset.toastArmed = "1";
    var timeout = parseInt(el.dataset.timeout || TOAST_TIMEOUT, 10);
    var timer = null;
    var start = function () { if (timeout > 0) timer = setTimeout(function () { dismissToast(el); }, timeout); };
    var stop = function () { clearTimeout(timer); };
    // 마우스를 올리거나 포커스하면 잠깐 멈춤
    el.addEventListener("mouseenter", stop);
    el.addEventListener("mouseleave", start);
    el.addEventListener("focusin", stop);
    el.addEventListener("focusout", start);
    start();
  }

  function toast(message, level) {
    level = level || "info";
    if (level === "error") level = "danger";
    var stack = document.getElementById("toast-stack");
    if (!stack || !message) return;
    var el = document.createElement("div");
    el.className = "toast toast-" + level;
    el.setAttribute("role", level === "danger" || level === "warning" ? "alert" : "status");
    el.setAttribute("data-toast", "");
    var icon = level === "success" ? "check" : level === "info" ? "info" : "alert";
    el.innerHTML = svg(icon) + '<p class="toast-message"></p><button type="button" class="toast-close" data-toast-close aria-label="알림 닫기">' + svg("x") + "</button>";
    el.querySelector(".toast-message").textContent = message;
    stack.appendChild(el);
    armToast(el);
    return el;
  }

  /* ───────── 드롭다운 / 토글 ───────── */
  function closeDropdown(root) {
    var menu = $("[data-dropdown-menu]", root);
    var btn = $("[data-dropdown-toggle]", root);
    if (menu) menu.hidden = true;
    if (btn) btn.setAttribute("aria-expanded", "false");
  }

  function closeAllDropdowns(except) {
    $all("[data-dropdown]").forEach(function (root) {
      if (root !== except) closeDropdown(root);
    });
  }

  function toggleDropdown(root) {
    var menu = $("[data-dropdown-menu]", root);
    var btn = $("[data-dropdown-toggle]", root);
    if (!menu) return;
    var willOpen = menu.hidden;
    closeAllDropdowns(root);
    menu.hidden = !willOpen;
    if (btn) btn.setAttribute("aria-expanded", String(willOpen));
    if (willOpen) {
      var first = $("a, button:not([disabled]), input", menu);
      // 키보드 사용자는 첫 항목으로 이동
      if (first && document.documentElement.dataset.input === "keyboard") first.focus();
    }
  }

  /* ───────── 모달 ───────── */
  var lastFocused = null;

  function openModal(id) {
    var modal = typeof id === "string" ? document.getElementById(id) : id;
    if (!modal) return;
    lastFocused = document.activeElement;
    modal.hidden = false;
    document.body.classList.add("modal-open");
    var focusable = $("[autofocus], input:not([type=hidden]), select, textarea, button:not([data-modal-close])", modal) || $("[data-modal-close]", modal);
    if (focusable) setTimeout(function () { focusable.focus(); }, 30);
    modal.dispatchEvent(new CustomEvent("poly:modal-open", { bubbles: true }));
  }

  function closeModal(id) {
    var modal = typeof id === "string" ? document.getElementById(id) : id;
    if (!modal || modal.hidden) return;
    modal.hidden = true;
    if (!$("[data-modal]:not([hidden])")) document.body.classList.remove("modal-open");
    if (lastFocused && lastFocused.focus) lastFocused.focus();
    modal.dispatchEvent(new CustomEvent("poly:modal-close", { bubbles: true }));
  }

  /* ───────── 이미지 미리보기 ───────── */
  function renderPreview(input) {
    var target = $(input.dataset.previewTarget);
    if (!target) return;
    var max = parseInt(input.dataset.previewMax || "10", 10);
    var files = Array.prototype.slice.call(input.files || []).filter(function (f) { return /^image\//.test(f.type); });
    // 이전 object URL 정리
    $all("img[data-object-url]", target).forEach(function (img) { URL.revokeObjectURL(img.src); });
    target.innerHTML = "";
    if (!files.length) { target.hidden = true; return; }
    target.hidden = false;
    target.classList.add("preview-grid");
    if (files.length > max) toast("사진은 최대 " + max + "장까지 올릴 수 있어요", "warning");
    files.slice(0, max).forEach(function (file, i) {
      var item = document.createElement("div");
      item.className = "preview-item";
      var img = document.createElement("img");
      img.src = URL.createObjectURL(file);
      img.alt = file.name;
      img.setAttribute("data-object-url", "");
      item.appendChild(img);
      if (i === 0) {
        var badge = document.createElement("span");
        badge.className = "preview-item-badge";
        badge.textContent = "대표";
        item.appendChild(badge);
      }
      target.appendChild(item);
    });
    input.dispatchEvent(new CustomEvent("poly:preview", { bubbles: true, detail: { files: files.slice(0, max) } }));
  }

  /* ───────── 텍스트영역 자동 높이 ───────── */
  function autoresize(el) {
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, parseInt(el.dataset.autoresizeMax || "200", 10)) + "px";
  }

  /* ───────── 초기화 (최초 + HTMX로 들어온 콘텐츠) ───────── */
  function init(root) {
    root = root || document;
    $all("[data-toast]", root).forEach(armToast);
    if (root.matches && root.matches("[data-toast]")) armToast(root);
    $all("textarea[data-autoresize]", root).forEach(autoresize);
  }

  /* ───────── 이벤트 위임 ───────── */
  // 확인창: 캡처 단계에서 먼저 처리 → 취소하면 htmx 요청/링크 이동도 막힘
  document.addEventListener("click", function (e) {
    var confirmEl = e.target.closest("a[data-confirm], button[data-confirm]");
    if (confirmEl && !confirmEl.closest("form[data-confirm]") && !window.confirm(confirmEl.dataset.confirm)) {
      e.preventDefault();
      e.stopImmediatePropagation();
    }
  }, true);

  document.addEventListener("click", function (e) {
    var t = e.target;

    // 토스트 닫기
    var tc = t.closest("[data-toast-close]");
    if (tc) { dismissToast(tc.closest("[data-toast]")); return; }

    // 모달 열기/닫기
    var mo = t.closest("[data-modal-open]");
    if (mo) { e.preventDefault(); openModal(mo.dataset.modalOpen); }
    var mc = t.closest("[data-modal-close]");
    if (mc) { e.preventDefault(); closeModal(mc.closest("[data-modal]")); return; }

    // 일반 토글
    var tg = t.closest("[data-toggle]");
    if (tg) {
      var target = $(tg.dataset.toggle);
      if (target) {
        target.hidden = !target.hidden;
        tg.setAttribute("aria-expanded", String(!target.hidden));
        if (!target.hidden) { var f = $("input, textarea, select", target); if (f) f.focus(); }
      }
    }

    // 드롭다운
    var dt = t.closest("[data-dropdown-toggle]");
    if (dt) {
      e.preventDefault();
      toggleDropdown(dt.closest("[data-dropdown]"));
      return;
    }
    // 메뉴 바깥 클릭 → 닫기 (메뉴 안의 링크/버튼 클릭도 닫힘)
    var inMenu = t.closest("[data-dropdown-menu]");
    if (!inMenu) closeAllDropdowns();
    else if (t.closest("a, button[type=submit]")) closeAllDropdowns();
  });

  // 폼 제출 확인창
  document.addEventListener("submit", function (e) {
    var form = e.target;
    if (form.matches("form[data-confirm]") && !window.confirm(form.dataset.confirm)) {
      e.preventDefault();
      e.stopImmediatePropagation();
    }
  }, true);

  document.addEventListener("keydown", function (e) {
    document.documentElement.dataset.input = "keyboard";
    if (e.key === "Escape") {
      var open = $all("[data-modal]:not([hidden])").pop();
      if (open) { closeModal(open); return; }
      var openMenu = $("[data-dropdown-menu]:not([hidden])");
      if (openMenu) {
        var root = openMenu.closest("[data-dropdown]");
        closeDropdown(root);
        var btn = $("[data-dropdown-toggle]", root);
        if (btn) btn.focus();
      }
    }
  });
  document.addEventListener("mousedown", function () { document.documentElement.dataset.input = "mouse"; });

  document.addEventListener("change", function (e) {
    if (e.target.matches("input[type=file][data-preview-target]")) renderPreview(e.target);
  });
  document.addEventListener("input", function (e) {
    if (e.target.matches("textarea[data-autoresize]")) autoresize(e.target);
  });

  /* ───────── HTMX 연동 ───────── */
  if (window.htmx) {
    // 요청 중 상단 로딩 바
    var pending = 0;
    // [data-silent] 요소(배지 폴링 등)는 로딩 바를 띄우지 않음
    var silent = function (e) { return e.detail && e.detail.elt && e.detail.elt.closest && e.detail.elt.closest("[data-silent]"); };
    document.addEventListener("htmx:beforeRequest", function (e) {
      if (silent(e)) return;
      pending++;
      document.body.classList.add("is-loading");
    });
    document.addEventListener("htmx:afterRequest", function (e) {
      if (silent(e)) return;
      pending = Math.max(0, pending - 1);
      if (!pending) document.body.classList.remove("is-loading");
    });
    // 서버 에러/네트워크 오류 안내
    document.addEventListener("htmx:responseError", function (e) {
      var s = e.detail.xhr ? e.detail.xhr.status : 0;
      if (s === 403) toast("권한이 없어요", "danger");
      else if (s === 404) toast("찾을 수 없는 페이지예요", "danger");
      else if (s === 429) toast("요청이 너무 많아요. 잠시 후 다시 시도해 주세요", "warning");
      else toast("요청을 처리하지 못했어요. 잠시 후 다시 시도해 주세요", "danger");
    });
    document.addEventListener("htmx:sendError", function () { toast("네트워크 연결을 확인해 주세요", "danger"); });
    // 로그인 필요 시 서버가 HX-Redirect를 주면 htmx가 처리. 이벤트 기반 토스트:
    document.body.addEventListener("showToast", function (e) {
      var d = e.detail || {};
      toast(d.message || d.value, d.level || "info");
    });
    // 새 콘텐츠 재초기화 (최초 로드 포함)
    window.htmx.onLoad(function (el) { init(el); });
  } else {
    document.addEventListener("DOMContentLoaded", function () { init(document); });
  }

  // 페이지 이동 시 모달/드롭다운 정리 (bfcache 복원 대비)
  window.addEventListener("pageshow", function () { closeAllDropdowns(); document.body.classList.remove("is-loading"); });

  /* ───────── 전역 API ───────── */
  window.Poly = {
    toast: toast,
    openModal: openModal,
    closeModal: closeModal,
    closeDropdowns: closeAllDropdowns,
    renderPreview: renderPreview,
    init: init,
  };
})();
