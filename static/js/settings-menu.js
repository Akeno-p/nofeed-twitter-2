// ---- 設定メニュー (歯車) ----
const $menu = $("#settings-menu");
const $toggle = $("#settings-toggle");
function setMenu(open) {
  $menu.prop("hidden", !open);
  $toggle.attr("aria-expanded", open);
}
$toggle.on("click", function (e) {
  e.stopPropagation();
  setMenu($menu.prop("hidden"));
});
$(document).on("click", function (e) {
  if (!$(e.target).closest("#settings-menu").length) setMenu(false);
});
$(document).on("keydown", function (e) {
  if (e.key === "Escape") setMenu(false);
});
