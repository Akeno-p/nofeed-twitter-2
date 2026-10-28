// ---- 元のツイートのウィンドウ (_reply_list.html の「…に対しての返信」) ----
// 見出しの隣の <template> に入れてある、元ツイートの全文と画像を、ウィンドウに写して開く。
const parentDialog = document.getElementById("parent-dialog");
function openParentDialog(btn) {
  const tpl = $(btn).next("template[data-parent-tpl]")[0];
  if (!tpl || !parentDialog) return;
  $("#parent-dialog-body").empty().append(tpl.content.cloneNode(true));
  parentDialog.scrollTop = 0;
  parentDialog.showModal();
}
function resetParentDialog() {
  $("#parent-dialog-body").empty();
}
