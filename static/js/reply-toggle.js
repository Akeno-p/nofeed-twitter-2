// ---- 返信欄の開閉 (_reply_list.html の「返信する」) ----
$(document).on("click", ".js-reply-toggle", function () {
  const $form = $(this).siblings(".js-reply-form");
  const open = $form.hasClass("hidden");
  $form.toggleClass("hidden", !open);
  $(this).attr("aria-expanded", open);
  if (open)
    $form
      .find("textarea")
      .each(function () {
        autoGrow(this);
      })
      .trigger("focus");
});
