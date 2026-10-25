// ---- 元のツイートのウィンドウ (_reply_list.html の「…に対しての返信」) ----
// 見出しの隣の <template> に入れてある、元ツイートの全文と画像を、ウィンドウに写して開く。
const parentDialog = document.getElementById("parent-dialog");
$(document).on("click", ".js-parent-open", function () {
  const tpl = $(this).next("template.js-parent-tpl")[0];
  if (!tpl || !parentDialog) return;
  $("#parent-dialog-body").empty().append(tpl.content.cloneNode(true));
  parentDialog.scrollTop = 0;
  parentDialog.showModal();
});
$("[data-parent-close]").on("click", function () {
  parentDialog.close();
});
$(parentDialog).on("click", function (e) {
  if (e.target === parentDialog) parentDialog.close(); // 外側クリックで閉じる
});
$(parentDialog).on("close", function () {
  $("#parent-dialog-body").empty();
});
