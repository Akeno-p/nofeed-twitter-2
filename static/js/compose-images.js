// ---- 画像の選択とプレビュー ----
// 投稿欄・返信欄ごとに選んだファイルを配列で持つ (input の files は直接いじれないため)
const picked = new WeakMap();
// 上限の枚数に達したら、画像の追加ボタンを押せなくする (外せば、また押せる)
function updateAddImage($form, count) {
  const full = count >= MAX_IMAGES;
  $form.find(".js-compose-file").prop("disabled", full);
  // 通常は押せる見た目 (cursor-pointer / hover の色)。上限のときは薄くして「押せない」カーソルにする
  $form
    .find(".js-add-image")
    .toggleClass("cursor-pointer hover:bg-slate-200", !full)
    .toggleClass("cursor-not-allowed opacity-40", full)
    .attr("aria-disabled", full ? "true" : null)
    .attr(
      "title",
      full
        ? "画像は" + MAX_IMAGES + "枚までです"
        : "画像を添付 (" + MAX_IMAGES + "枚まで)",
    );
}
// プレビュー用の一時的な画像URL。拡大表示でも同じURLを使うので、読み込み後ではなく、
// プレビューを作り直すとき (画像を外した・投稿した) に破棄する。
const previewUrls = new WeakMap();
function renderPreviews($form) {
  const files = picked.get($form[0]) || [];
  updateAddImage($form, files.length);
  (previewUrls.get($form[0]) || []).forEach(function (u) {
    URL.revokeObjectURL(u);
  });
  const urls = [];
  previewUrls.set($form[0], urls);
  const $list = $form.find(".js-previews").empty();
  files.forEach(function (file, i) {
    const url = URL.createObjectURL(file);
    urls.push(url);
    const $li = $("<li>").addClass("relative");
    // 画像を押すと拡大表示 (投稿済みの画像と同じ部品。.js-gallery 内の .js-zoom が対象)
    $("<button>")
      .attr({ type: "button", "aria-label": "画像 " + (i + 1) + " を拡大" })
      .addClass(
        "js-zoom block cursor-zoom-in rounded-lg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-500",
      )
      .append(
        $("<img>")
          .attr({ src: url, alt: "添付画像 " + (i + 1) })
          .addClass("size-32 rounded-lg object-cover"),
      )
      .appendTo($li);
    $("<button>")
      .attr({ type: "button", "aria-label": "画像 " + (i + 1) + " を外す" })
      .addClass(
        "absolute -right-2 -top-2 flex size-6 cursor-pointer items-center justify-center rounded-full bg-slate-700 text-sm text-white",
      )
      .text("×")
      .on("click", function () {
        files.splice(i, 1);
        renderPreviews($form);
      })
      .appendTo($li);
    $list.append($li);
  });
}

function addComposeImages(input) {
  const $form = $(input).closest(COMPOSE);
  const files = picked.get($form[0]) || [];
  const incoming = Array.from(input.files);
  const room = MAX_IMAGES - files.length;
  clearFormError($form);
  if (incoming.length > room)
    setFormError($form, "画像は" + MAX_IMAGES + "枚までです", "images");
  files.push.apply(files, incoming.slice(0, room));
  picked.set($form[0], files);
  input.value = "";
  renderPreviews($form);
}
