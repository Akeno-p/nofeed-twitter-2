// ---- 「ツイート取得」「リプライ取得」 (tweets.html / replies.html のボタンと、_sync_confirm.html) ----
// ボタンを押すと、まず料金の確認を出す。「取得する」を押して初めて Xに取りに行く。
function runSync($btn) {
  const $label = $btn.find(".js-sync-label");
  const original = $label.text();
  clearError();
  $btn.prop("disabled", true);
  $label.text("取得中…");
  $.post($btn.data("url"))
    .done(function (res) {
      $($btn.data("target")).html(res.html);
      showToast("成功", "success");
    })
    .fail(function (xhr) {
      const e = errorOf(xhr);
      showError(e[0], e[1]); // 理由 (クレジット不足・連携切れなど) は上の帯に出る
      showToast("失敗", "failure");
    })
    .always(function () {
      $btn.prop("disabled", false);
      $label.text(original);
    });
}

$(".js-sync").on("click", function () {
  const $btn = $(this);
  const confirmDialog = document.querySelector($btn.data("confirm"));
  if (!confirmDialog) return;
  $(confirmDialog).data("sync-btn", $btn);
  confirmDialog.showModal();
  // 開いた直後に Enter を押しても取得(課金)が始まらないよう、ボタンではなくウィンドウに置く
  confirmDialog.focus();
});
$("[data-sync-confirm]").on("click", function () {
  const $dlg = $(this).closest("dialog");
  const $btn = $dlg.data("sync-btn");
  $dlg[0].close();
  if ($btn) runSync($btn);
});
$("#sync-confirm-dialog").on("click", function (e) {
  if (e.target === this) this.close(); // 外側クリックはキャンセル扱い
});
