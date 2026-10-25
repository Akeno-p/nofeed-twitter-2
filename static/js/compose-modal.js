// ---- 投稿モーダル ----
const dialog = document.getElementById("compose-dialog");
function openComposeModal() {
  if (!dialog) return;
  dialog.showModal();
  $(dialog)
    .find("textarea")
    .each(function () {
      autoGrow(this);
    })
    .trigger("focus");
}
