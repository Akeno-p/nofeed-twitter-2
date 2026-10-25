// ---- 投稿モーダル ----
const dialog = document.getElementById("compose-dialog");
$("[data-open-compose]").on("click", function () {
  if (!dialog) return;
  dialog.showModal();
  $(dialog)
    .find("textarea")
    .each(function () {
      autoGrow(this);
    })
    .trigger("focus");
});
$("[data-close-compose]").on("click", function () {
  dialog.close();
});
$(dialog).on("click", function (e) {
  if (e.target === dialog) dialog.close(); // 外側クリックで閉じる
});
