(function () {
    var noEmailTelegram = document.getElementById('telegram-config').getAttribute('data-config-nomail') === 'True';

    // Hacky workarounds lol
    if (noEmailTelegram) {
        var delivery_mode = document.getElementById('id_telegram_delivery_mode');
        delivery_mode.value = 'telegram_only';
        delivery_mode.readonly = true;
        delivery_mode.onmousedown = function (e) {
            e.preventDefault();
            return false;
        }
        delivery_mode.onkeydown = function (e) {
            e.preventDefault();
            return false;
        }
    }
})();