// ---- 投稿欄 (_compose.html) と返信欄 (_reply_list.html) の処理 ----
const MAX_IMAGES = 4;
const COMPOSE = "[data-compose], [data-reply-form]"; // 投稿欄と返信欄の外側の箱

// ---- 入力エラー: 該当の入力欄を赤くし、ボタンの下に理由を出す ----
function setFormError($form, msg, field) {
  clearFormError($form);
  $form.find("[data-form-error]").text(msg).removeClass("hidden");
  if (field === "text")
    $form.find("[data-compose-text]").attr("aria-invalid", "true");
}
function clearFormError($form) {
  $form.find("[data-form-error]").addClass("hidden").empty();
  $form.find("[aria-invalid]").removeAttr("aria-invalid");
}

// ---- 文字数カウンタ ----
function updateCount($form) {
  const len = Array.from($form.find("[data-compose-text]").val()).length;
  const max = Number($form.find("[data-compose-text]").attr("maxlength"));
  $form
    .find("[data-count]")
    .text(len + "/" + max)
    .toggleClass("text-red-600", len >= max);
}

// ---- 投稿・返信の送信 ----
function submitCompose($form) {
  const $submit = $form.find("[data-compose-submit]");
  const text = $form.find("[data-compose-text]").val();
  const files = picked.get($form[0]) || [];

  if (!text.trim() && !files.length) {
    setFormError($form, "本文を入力してください", "text");
    return;
  }

  const data = new FormData();
  data.append("text", text);
  if ($form.attr("data-reply-to"))
    data.append("reply_to", $form.attr("data-reply-to"));
  files.forEach(function (f) {
    data.append("images", f);
  });

  clearError();
  clearFormError($form);
  $submit.prop("disabled", true);
  $.ajax({
    url: $form.attr("data-url"),
    method: "POST",
    data: data,
    processData: false,
    contentType: false,
  })
    .done(function (res) {
      $form
        .find("[data-compose-text]")
        .val("")
        .each(function () {
          autoGrow(this);
        });
      picked.delete($form[0]);
      renderPreviews($form);
      updateCount($form);
      if ($form.is("[data-reply-form]")) {
        $("#reply-list").html(res.html);
      } else {
        $("#tweet-list").html(res.html); // ツイート画面にいるときだけ一覧が差し替わる
        if (dialog && dialog.open) dialog.close();
      }
      showToast("成功", "success");
    })
    .fail(function (xhr) {
      const body = xhr.responseJSON || {};
      showToast("失敗", "failure");
      if (body.field) {
        // 入力の問題: 閉じずにその場で直せるよう、フォームの中に表示する
        setFormError($form, body.error, body.field);
        return;
      }
      const e = errorOf(xhr);
      if (dialog && dialog.open) dialog.close();
      showError(e[0], e[1]);
    })
    .always(function () {
      $submit.prop("disabled", false);
    });
}
