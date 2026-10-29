// Small behaviours for our pages. No inline scripts anywhere: the
// Content-Security-Policy only allows scripts from our own static files.
// Everything is wired through data-* attributes and event delegation, so it
// also works on content that htmx swaps in.
(function () {
  "use strict";

  // <select data-autosubmit>: submit the form when the choice changes
  // (the language switch).
  document.addEventListener("change", function (event) {
    if (event.target.matches("select[data-autosubmit]")) {
      event.target.form.submit();
    }
  });

  // <input data-select-on-click>: select the whole value (links to copy).
  document.addEventListener("click", function (event) {
    if (event.target.matches("input[data-select-on-click]")) {
      event.target.select();
    }
  });

  // <button data-copy-target="id" data-copied="Copied">: copy that input's value.
  document.addEventListener("click", function (event) {
    var button = event.target.closest("button[data-copy-target]");
    if (!button) return;
    var input = document.getElementById(button.dataset.copyTarget);
    if (!input || !navigator.clipboard) return;
    navigator.clipboard.writeText(input.value).then(function () {
      button.textContent = button.dataset.copied;
    });
  });

  // Booking page: running total = price per machine × ticked machines.
  // <p id="booking-total" data-price data-label data-money> and
  // <input data-machine> checkboxes. Without JavaScript the server checks
  // the total on submit.
  function updateBookingTotal() {
    var total = document.getElementById("booking-total");
    if (!total) return;
    var ticked = document.querySelectorAll("input[data-machine]:checked").length;
    var amount = total.dataset.money.replace("0", String(ticked * Number(total.dataset.price)));
    total.textContent = total.dataset.label + ": " + amount;
    total.hidden = false;
  }
  document.addEventListener("change", function (event) {
    if (event.target.matches("input[data-machine]")) updateBookingTotal();
  });
  document.addEventListener("DOMContentLoaded", updateBookingTotal);

  // "Change balance": <p id="balance-preview" data-balance data-money
  // data-label> shows "Balance: 120 ₽ → 170 ₽" while the admin types.
  function money(template, amount) {
    return (amount < 0 ? "−" : "") + template.replace("0", String(Math.abs(amount)));
  }
  function updateBalancePreview() {
    var preview = document.getElementById("balance-preview");
    var form = document.querySelector("form[data-balance-form]");
    if (!preview || !form) return;
    var current = Number(preview.dataset.balance);
    var amount = parseInt(form.querySelector("[data-balance-amount]").value, 10);
    var direction = form.querySelector("input[name=direction]:checked");
    var text = preview.dataset.label + ": " + money(preview.dataset.money, current);
    if (amount > 0 && direction) {
      var next = current + (direction.value === "subtract" ? -amount : amount);
      text += " → " + money(preview.dataset.money, next);
    }
    preview.textContent = text;
  }
  ["input", "change"].forEach(function (type) {
    document.addEventListener(type, function (event) {
      if (event.target.closest("form[data-balance-form]")) updateBalancePreview();
    });
  });
  document.addEventListener("DOMContentLoaded", updateBalancePreview);

  // --- Installable app ---------------------------------------------------------

  // The service worker only keeps an offline page (templates/core/sw.js).
  var thisScript = document.currentScript;
  if ("serviceWorker" in navigator && thisScript && thisScript.dataset.serviceWorker) {
    window.addEventListener("load", function () {
      navigator.serviceWorker.register(thisScript.dataset.serviceWorker, { scope: "/" });
    });
  }

  // Install guide (templates/core/_install_guide.html): one variant for the
  // phone at hand, never inside the installed app, gone after "Got it".
  var DISMISSED = "installGuideDismissed";
  var installPrompt = null;

  function storage(action, value) {
    try {
      return action === "get"
        ? window.localStorage.getItem(DISMISSED)
        : window.localStorage.setItem(DISMISSED, value);
    } catch (error) {
      return null; // private mode or storage blocked: just show the guide
    }
  }

  function isInstalled() {
    return window.matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
  }

  function platform() {
    var ua = navigator.userAgent;
    // In-app browsers cannot install web apps.
    if (/Telegram|Instagram|FBAN|FBAV|FB_IAB|VKClient|vkclient|WhatsApp|Line\//i.test(ua)) {
      return "in-app";
    }
    var ios = /iPhone|iPad|iPod/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1);
    if (ios) return "ios";
    return null; // Android Chrome shows its variant when it offers installation
  }

  function showGuide(variant) {
    var guide = document.getElementById("install-guide");
    if (!guide || isInstalled() || storage("get")) return;
    guide.querySelectorAll("[data-install-variant]").forEach(function (part) {
      part.hidden = part.dataset.installVariant !== variant;
    });
    guide.hidden = false;
  }

  document.addEventListener("DOMContentLoaded", function () {
    var variant = platform();
    if (variant) showGuide(variant);
  });

  // Android Chrome: it tells us the app can be installed; show our button.
  window.addEventListener("beforeinstallprompt", function (event) {
    event.preventDefault();
    installPrompt = event;
    showGuide("android");
  });

  document.addEventListener("click", function (event) {
    if (event.target.closest("[data-install-button]") && installPrompt) {
      installPrompt.prompt();
      installPrompt.userChoice.then(function () {
        installPrompt = null;
        document.getElementById("install-guide").hidden = true;
      });
    }
    if (event.target.closest("[data-install-dismiss]")) {
      storage("set", "1");
      document.getElementById("install-guide").hidden = true;
    }
  });

  window.addEventListener("appinstalled", function () {
    var guide = document.getElementById("install-guide");
    if (guide) guide.hidden = true;
  });
})();
