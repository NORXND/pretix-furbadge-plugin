(function () {
    // Get the Telegram info container
    var tgBox = document.querySelector('.furbadge-telegram-connect');
    if (!tgBox) return;

    var username = tgBox.getAttribute('data-username');

    // Select the list (dl)
    var dl = document.querySelector('dl, .dl-horizontal');
    if (!dl) return;

    var telegramEmail = document.getElementById('telegram-config').getAttribute('data-config-email');
    var noEmailTelegram = document.getElementById('telegram-config').getAttribute('data-config-nomail') === 'True';

    // Handle the "Email" cleanup
    var dts = dl.getElementsByTagName('dt');
    for (var i = 0; i < dts.length; i++) {
        var dt = dts[i];
        var dd = dt.nextElementSibling; // Get the corresponding <dd>

        if (dt.textContent.trim() === 'Email' && dd) {
            if (dd.textContent.trim() === telegramEmail) {
                // Remove the <dt> and the <dd>
                dt.style.display = 'none';
                dd.style.display = 'none';
                noEmailTelegram = true;
            }
        }
    }

    var inputs = document.querySelectorAll('input[value="' + telegramEmail + '"]');
    for (var i = 0; i < inputs.length; i++) {
        var input = inputs[i];
        input.value = '';
    }

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

    // Add Telegram info if linked
    if (username) {
        var newDt = document.createElement('dt');
        newDt.textContent = 'Telegram';
        var newDd = document.createElement('dd');
        newDd.textContent = '@' + username;

        dl.appendChild(newDt);
        dl.appendChild(newDd);
    }
})();