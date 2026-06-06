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