// ---- 画像の拡大表示 (_media.html の画像と、投稿欄のプレビュー画像) ----
const lightbox = document.getElementById("lightbox");
let galleryUrls = [];
let galleryIndex = 0;

// X の画像は、?name=large を付けると大きい版が取れる。取れなければ元の画像のまま使う。
function largeUrl(url) {
  try {
    const u = new URL(url);
    if (u.hostname === "pbs.twimg.com" && !u.searchParams.has("name")) {
      u.searchParams.set("name", "large");
      return u.toString();
    }
  } catch (e) {}
  return url;
}

function showGalleryImage() {
  const thumb = galleryUrls[galleryIndex];
  const big = largeUrl(thumb);
  const $img = $("#lightbox-img");
  $img.attr({ src: thumb, alt: "添付画像 " + (galleryIndex + 1) }); // まず今の画像を出して、すぐ見せる
  if (big !== thumb) {
    const loader = new Image();
    loader.referrerPolicy = "no-referrer";
    loader.onload = function () {
      // 読み込み中に別の画像へ切り替えていなければ、大きい版に差し替える
      if (galleryUrls[galleryIndex] === thumb) $img.attr("src", big);
    };
    loader.src = big;
  }
  const many = galleryUrls.length > 1;
  $("#lightbox-prev, #lightbox-next, #lightbox-count").prop("hidden", !many);
  $("#lightbox-count").text(galleryIndex + 1 + " / " + galleryUrls.length);
}

function stepGallery(delta) {
  if (galleryUrls.length < 2) return;
  galleryIndex =
    (galleryIndex + delta + galleryUrls.length) % galleryUrls.length;
  showGalleryImage();
}

$(document).on("click", ".js-zoom", function () {
  const $gallery = $(this).closest(".js-gallery");
  galleryUrls = $gallery
    .find("img")
    .map(function () {
      return this.getAttribute("src");
    })
    .get();
  galleryIndex = $gallery.find(".js-zoom").index(this);
  showGalleryImage();
  lightbox.showModal();
  $("html").addClass("overflow-hidden"); // 後ろのページが一緒に動かないようにする
});
$(lightbox).on("close", function () {
  $("html").removeClass("overflow-hidden");
  $("#lightbox-img").removeAttr("src");
});
$("[data-lightbox-close]").on("click", function () {
  lightbox.close();
});
$("#lightbox-prev").on("click", function () {
  stepGallery(-1);
});
$("#lightbox-next").on("click", function () {
  stepGallery(1);
});
$(lightbox).on("click", function (e) {
  // 画像やボタン以外 (外側) を押したら閉じる
  if (e.target === lightbox || $(e.target).hasClass("js-lightbox-bg"))
    lightbox.close();
});
$(document).on("keydown", function (e) {
  if (!lightbox || !lightbox.open) return;
  if (e.key === "ArrowLeft") stepGallery(-1);
  if (e.key === "ArrowRight") stepGallery(1);
});
