// ---- 設定メニュー (歯車) ----
const $menu = $("#settings-menu");
const $toggle = $("#settings-toggle");
function setMenu(open) {
  $menu.prop("hidden", !open);
  $toggle.attr("aria-expanded", open);
}
