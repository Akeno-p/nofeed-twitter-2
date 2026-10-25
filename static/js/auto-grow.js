// ---- 入力欄の高さ: 入力した行数 (折り返しも含む) に合わせて自動で伸び縮みさせる ----
// 画面に出ていない入力欄は高さが測れないので、何もしない (表示するときに呼び直す)。
function autoGrow(el) {
  if (!el || el.offsetParent === null) return;
  el.style.height = "auto"; // いったん縮めてから、中身の高さを測り直す
  const borders = el.offsetHeight - el.clientHeight; // 枠線の分 (border-box なので足す)
  el.style.height = el.scrollHeight + borders + "px";
  // 上限 (max-height) を超えたときだけ、スクロールバーを出す
  el.style.overflowY =
    el.scrollHeight > el.clientHeight + 1 ? "auto" : "hidden";
}
$(document).on("input", ".js-compose-text", function () {
  autoGrow(this);
});
$(window).on("resize", function () {
  $(".js-compose-text").each(function () {
    autoGrow(this);
  }); // 幅が変わると折り返しも変わる
});
