// ---- 返信欄の開閉 (_reply_list.html の「返信する」) ----
function toggleReplyForm(btn) {
  const $form = $(btn).siblings("[data-reply-form]");
  const open = $form.hasClass("hidden");
  $form.toggleClass("hidden", !open);
  $(btn).attr("aria-expanded", open);
  if (open)
    $form
      .find("textarea")
      .each(function () {
        autoGrow(this);
      })
      .trigger("focus");
}
