// ---- 通知: 画面下の中央に少しの間だけ「成功」「失敗」を出す ----
let toastTimer = null;
const TOAST_COLORS = { success: "bg-sky-600", failure: "bg-slate-700" };
function showToast(text, kind) {
  const $t = $("#toast");
  clearTimeout(toastTimer);
  $t.removeClass(Object.values(TOAST_COLORS).join(" "))
    .addClass(TOAST_COLORS[kind])
    .text(text)
    .removeClass("translate-y-3.5 opacity-0");
  toastTimer = setTimeout(function () {
    $t.addClass("translate-y-3.5 opacity-0");
  }, 2500);
}
