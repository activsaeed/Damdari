const wrapper = document.getElementById('wrapper');
const sidebarWrapper = document.getElementById('sidebar-wrapper');
const menuToggle = document.getElementById('menu-toggle');
const closeSidebar = document.getElementById('close-sidebar');
const overlay = document.getElementById('sidebar-overlay');

// باز کردن منو در موبایل
menuToggle.addEventListener('click', function(e) {
    e.preventDefault();
    sidebarWrapper.classList.add('toggled');
    overlay.classList.remove('d-none');
});

// بستن منو با دکمه ضربدر
closeSidebar.addEventListener('click', function(e) {
    e.preventDefault();
    sidebarWrapper.classList.remove('toggled');
    overlay.classList.add('d-none');
});

// بستن منو با کلیک روی فضای خالی (لایه تاریک)
overlay.addEventListener('click', function() {
    sidebarWrapper.classList.remove('toggled');
    overlay.classList.add('d-none');
});

// نمایش/مخفی کردن وضعیت بارگذاری
function showLoading(el) { if (el) { el.style.opacity = '0.5'; el.style.pointerEvents = 'none'; } }
function hideLoading(el) { if (el) { el.style.opacity = '1'; el.style.pointerEvents = ''; } }

// افزودن دکمه لغو به همه مودال‌ها
document.addEventListener('DOMContentLoaded', function() {
    document.querySelectorAll('.modal-footer').forEach(function(footer) {
        var btn = footer.querySelector('button[type="submit"]');
        if (btn && !footer.querySelector('.btn-cancel')) {
            var cancel = document.createElement('button');
            cancel.type = 'button';
            cancel.className = 'btn btn-secondary btn-cancel';
            cancel.textContent = 'لغو';
            cancel.setAttribute('data-bs-dismiss', 'modal');
            footer.insertBefore(cancel, btn);
        }
    });
});

function formatCurrency(input) {
    var raw = input.value.replace(/,/g, '').replace(/[^0-9.]/g, '');
    if (raw) {
        var parts = raw.split('.');
        parts[0] = Number(parts[0]).toLocaleString('en-US');
        input.value = parts.join('.');
    }
    var hidden = input.closest('div').querySelector('input[type="hidden"]');
    if (!hidden) hidden = input.parentElement.querySelector('input[type="hidden"]');
    if (!hidden) hidden = document.getElementById('raw_' + input.id);
    if (hidden) {
        hidden.value = raw;
    }
}