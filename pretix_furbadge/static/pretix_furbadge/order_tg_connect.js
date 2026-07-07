(function () {
    var box = document.getElementById('furbadge-tg-consent');
    var btn = document.getElementById('furbadge-tg-connect-btn');
    if (!box || !btn) return;
    box.addEventListener('change', function () {
        btn.classList.toggle('disabled', !box.checked);
        if (box.checked) {
            btn.href = btn.href.split('?')[0] + '?consent=1';
        } else {
            btn.href = btn.href.split('?')[0];
        }
    });
    btn.addEventListener('click', function (e) {
        if (btn.classList.contains('disabled')) e.preventDefault();
    });
})();