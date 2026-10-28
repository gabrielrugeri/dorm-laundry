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
})();
