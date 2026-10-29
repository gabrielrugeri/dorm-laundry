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
})();
