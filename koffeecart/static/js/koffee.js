// Small page behaviours. No jQuery, and no inline scripts: the Content-Security-Policy
// only allows scripts loaded from our own static files.
document.addEventListener('DOMContentLoaded', () => {
  // Product gallery: a click on a thumbnail shows that image in the main frame.
  const main = document.querySelector('[data-gallery-main]');
  const thumbs = document.querySelectorAll('[data-gallery-thumb]');
  thumbs.forEach((thumb) => {
    thumb.addEventListener('click', (event) => {
      event.preventDefault();
      if (main) main.src = thumb.href;
      thumbs.forEach((t) => t.classList.toggle('active', t === thumb));
    });
  });

  // Quantity picker on the product page: the -/+ buttons stay within the input's min and max.
  document.querySelectorAll('[data-qty]').forEach((group) => {
    const input = group.querySelector('input');
    group.querySelectorAll('[data-qty-step]').forEach((button) => {
      button.addEventListener('click', () => {
        const min = Number(input.min) || 1;
        const max = Number(input.max) || 99;
        const value = (Number(input.value) || min) + Number(button.dataset.qtyStep);
        input.value = Math.min(max, Math.max(min, value));
      });
    });
  });

  // Invoice page: print button.
  document.querySelectorAll('[data-print]').forEach((button) => {
    button.addEventListener('click', () => window.print());
  });
});
