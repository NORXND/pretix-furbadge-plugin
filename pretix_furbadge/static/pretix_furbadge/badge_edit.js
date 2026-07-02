document.addEventListener("DOMContentLoaded", function () {
    var avatarInput = document.getElementById('avatar-input');
    var imageToCrop = document.getElementById('image-to-crop');
    var btnCrop = document.getElementById('btn-crop');
    var badgeTextInput = document.getElementById('id_badge_text');
    var charCount = document.getElementById('char-count');
    var cropper;

    // Handle text character counting
    if (badgeTextInput) {
        var updateCount = function () {
            var len = badgeTextInput.value.length;
            charCount.textContent = len;
            if (len > 32) {
                charCount.style.color = 'red';
            } else {
                charCount.style.color = '';
            }
        };
        badgeTextInput.addEventListener('input', updateCount);
        updateCount();
    }

    // Handle public list preferences
    var chkPublicList = document.getElementById('id_show_in_public_list');
    var chkTelegramPublic = document.getElementById('id_show_telegram_in_public_list');

    if (chkPublicList && chkTelegramPublic) {
        var toggleTelegramVisibility = function () {
            var wrapper = chkTelegramPublic.closest('.form-group');
            if (wrapper) {
                if (chkPublicList.checked) {
                    wrapper.style.display = 'block';
                } else {
                    wrapper.style.display = 'none';
                    chkTelegramPublic.checked = false;
                }
            }
        };
        chkPublicList.addEventListener('change', toggleTelegramVisibility);
        toggleTelegramVisibility();
    }

    // Fixed Preview Refresh Target (Using the iframes)
    var btnRefresh = document.getElementById('btn-refresh-preview');
    if (btnRefresh) {
        btnRefresh.addEventListener('click', function () {
            var frame = document.getElementById('badge-preview-frame');
            var frameLarge = document.getElementById('badge-preview-frame-large');
            var timestamp = '?t=' + new Date().getTime();

            if (frame) {
                var currentSrc = frame.src.split('?')[0];
                frame.src = currentSrc + timestamp;
            }
            if (frameLarge) {
                var currentLargeSrc = frameLarge.src.split('?')[0];
                frameLarge.src = currentLargeSrc + timestamp;
            }
        });
    }

    // Cropper.js Logic
    if (avatarInput) {
        avatarInput.addEventListener('change', function (e) {
            var files = e.target.files;
            if (files && files.length > 0) {
                var file = files[0];
                var reader = new FileReader();
                reader.onload = function (event) {
                    imageToCrop.src = event.target.result;
                    // Show Bootstrap Modal safely
                    $('#cropModal').modal('show');
                };
                reader.readAsDataURL(file);
            }
        });
    }

    $('#cropModal').on('shown.bs.modal', function () {
        const form = document.getElementById("badge-form");

        const avatarWidth = Number(form.dataset.avatarWidth);
        const avatarHeight = Number(form.dataset.avatarHeight);

        console.log(avatarWidth, avatarHeight);

        if (typeof Cropper !== "undefined") {
            cropper = new Cropper(imageToCrop, {
                aspectRatio: avatarWidth / avatarHeight,
                viewMode: 1,
                autoCropArea: 1,
                dragMode: "move",
            });
        } else {
            console.error("Cropper.js failed to load.");
        }
    }).on('hidden.bs.modal', function () {
        if (cropper) {
            cropper.destroy();
            cropper = null;
        }
        // reset input so the user can re-upload the same file if needed
        if (avatarInput) avatarInput.value = '';
    });

    if (btnCrop) {
        btnCrop.addEventListener('click', function () {
            if (!cropper) return;

            var canvas = cropper.getCroppedCanvas({
                width: 600,
                height: 600
            });

            var dataUrl = canvas.toDataURL('image/png');

            btnCrop.disabled = true;
            btnCrop.textContent = 'Uploading...';

            var formData = new FormData();
            formData.append('image_data', dataUrl);

            // 1. Safely extract values directly from DOM elements
            var badgeForm = document.getElementById('badge-form');
            var uploadUrl = badgeForm && badgeForm.dataset.uploadUrl ? badgeForm.dataset.uploadUrl : window.location.pathname;

            var csrfTokenElement = document.querySelector('[name=csrfmiddlewaretoken]');
            var csrfToken = csrfTokenElement ? csrfTokenElement.value : '';

            formData.append('csrfmiddlewaretoken', csrfToken);

            // 2. Fetch using our local configuration variable
            fetch(uploadUrl, {
                method: 'POST',
                body: formData,
                headers: {
                    'X-Requested-With': 'XMLHttpRequest'
                }
            })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        var currentAvatar = document.getElementById('current-avatar');
                        if (currentAvatar) {
                            currentAvatar.src = dataUrl;
                        } else {
                            var container = document.querySelector('.avatar-preview-container');
                            if (container) {
                                container.innerHTML = '<img id="current-avatar" src="' + dataUrl + '" alt="Avatar" class="img-responsive img-thumbnail" style="max-width: 200px;">';
                            }
                        }
                        $('#cropModal').modal('hide');

                        // Auto-trigger preview frame updates on successful upload
                        if (btnRefresh) btnRefresh.click();
                    } else {
                        alert('Upload failed: ' + (data.error || 'Unknown error'));
                    }
                })
                .catch(err => {
                    console.error(err);
                    alert('Upload failed. Please try again.');
                })
                .finally(() => {
                    btnCrop.disabled = false;
                    btnCrop.textContent = 'Crop & Upload';
                });
        });
    }
});