// nofeed-twitter のフロント処理 (jQuery)
$(function () {
  const MAX_IMAGES = 4;

  // ---- CSRF: すべての POST にトークンを付ける ----
  const csrf = $('meta[name="csrf-token"]').attr("content");
  $.ajaxSetup({
    beforeSend: function (xhr, settings) {
      if (!/^(GET|HEAD|OPTIONS)$/i.test(settings.type)) {
        xhr.setRequestHeader("X-CSRFToken", csrf);
        xhr.setRequestHeader("X-Requested-With", "XMLHttpRequest");
      }
    },
  });

  // ---- エラー表示 ----
  const $banner = $("#error-banner");
  function showError(msg, reconnect) {
    $banner.empty().append($("<span>").text(msg));
    if (reconnect) {
      $banner.append(
        $("<a>").attr("href", "/x/connect/").addClass("ml-2 underline").text("連携し直す")
      );
    }
    $banner.removeClass("hidden").addClass("flex");
    $banner[0] && $banner[0].scrollIntoView({ block: "nearest" });
  }
  function clearError() {
    $banner.addClass("hidden").removeClass("flex").empty();
  }
  function errorOf(xhr) {
    const body = xhr.responseJSON || {};
    return [body.error || "通信に失敗しました。もう一度お試しください。", !!body.needs_reconnect];
  }

  // ---- 入力エラー: 該当の入力欄を赤くし、ボタンの下に理由を出す ----
  function setFormError($form, msg, field) {
    clearFormError($form);
    $form.find(".js-form-error").text(msg).removeClass("hidden");
    if (field === "text") $form.find(".js-compose-text").attr("aria-invalid", "true");
  }
  function clearFormError($form) {
    $form.find(".js-form-error").addClass("hidden").empty();
    $form.find("[aria-invalid]").removeAttr("aria-invalid");
  }

  // ---- 通知: 画面下の中央に少しの間だけ「成功」「失敗」を出す ----
  let toastTimer = null;
  const TOAST_COLORS = { success: "bg-sky-500", failure: "bg-slate-700" };
  function showToast(text, kind) {
    const $t = $("#toast");
    clearTimeout(toastTimer);
    $t.removeClass(Object.values(TOAST_COLORS).join(" "))
      .addClass(TOAST_COLORS[kind])
      .text(text)
      .removeClass("translate-y-3 opacity-0");
    toastTimer = setTimeout(function () {
      $t.addClass("translate-y-3 opacity-0");
    }, 2500);
  }

  // ---- 画像の拡大表示 ----
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
    galleryIndex = (galleryIndex + delta + galleryUrls.length) % galleryUrls.length;
    showGalleryImage();
  }

  $(document).on("click", ".js-zoom", function () {
    const $gallery = $(this).closest(".js-gallery");
    galleryUrls = $gallery.find("img").map(function () { return this.getAttribute("src"); }).get();
    galleryIndex = $gallery.find(".js-zoom").index(this);
    showGalleryImage();
    lightbox.showModal();
    $("html").addClass("overflow-hidden"); // 後ろのページが一緒に動かないようにする
  });
  $(lightbox).on("close", function () {
    $("html").removeClass("overflow-hidden");
    $("#lightbox-img").removeAttr("src");
  });
  $("[data-lightbox-close]").on("click", function () { lightbox.close(); });
  $("#lightbox-prev").on("click", function () { stepGallery(-1); });
  $("#lightbox-next").on("click", function () { stepGallery(1); });
  $(lightbox).on("click", function (e) {
    // 画像やボタン以外 (外側) を押したら閉じる
    if (e.target === lightbox || $(e.target).hasClass("js-lightbox-bg")) lightbox.close();
  });
  $(document).on("keydown", function (e) {
    if (!lightbox || !lightbox.open) return;
    if (e.key === "ArrowLeft") stepGallery(-1);
    if (e.key === "ArrowRight") stepGallery(1);
  });

  // ---- 元のツイートのウィンドウ ----
  // 見出しの隣の <template> に入れてある、元ツイートの全文と画像を、ウィンドウに写して開く。
  const parentDialog = document.getElementById("parent-dialog");
  $(document).on("click", ".js-parent-open", function () {
    const tpl = $(this).next("template.js-parent-tpl")[0];
    if (!tpl || !parentDialog) return;
    $("#parent-dialog-body").empty().append(tpl.content.cloneNode(true));
    parentDialog.scrollTop = 0;
    parentDialog.showModal();
  });
  $("[data-parent-close]").on("click", function () { parentDialog.close(); });
  $(parentDialog).on("click", function (e) {
    if (e.target === parentDialog) parentDialog.close(); // 外側クリックで閉じる
  });
  $(parentDialog).on("close", function () { $("#parent-dialog-body").empty(); });

  // ---- 投稿日時: 「今」「◯分」「◯時間」を、開いたままでも更新する ----
  // 判定の基準は サーバー (core_tags.time_label) と同じ。24時間以上は、サーバーが出した日付を使う。
  function updateTimes() {
    const now = Date.now();
    $("time.js-reltime").each(function () {
      const seconds = (now - Date.parse($(this).attr("datetime"))) / 1000;
      let label;
      if (seconds < 60) label = "今";
      else if (seconds < 3600) label = Math.floor(seconds / 60) + "分";
      else if (seconds < 86400) label = Math.floor(seconds / 3600) + "時間";
      else label = $(this).attr("data-abs");
      if ($(this).text() !== label) $(this).text(label);
    });
  }
  setInterval(updateTimes, 30000);
  $(document).on("visibilitychange", function () {
    if (!document.hidden) updateTimes(); // 別のタブから戻ったら、すぐ最新にする
  });

  // ---- 確認ダイアログ付きフォーム ----
  $(document).on("submit", "form[data-confirm]", function (e) {
    if (!window.confirm($(this).data("confirm"))) e.preventDefault();
  });

  // ---- 設定メニュー (歯車) ----
  const $menu = $("#settings-menu");
  const $toggle = $("#settings-toggle");
  function setMenu(open) {
    $menu.prop("hidden", !open);
    $toggle.attr("aria-expanded", open);
  }
  $toggle.on("click", function (e) {
    e.stopPropagation();
    setMenu($menu.prop("hidden"));
  });
  $(document).on("click", function (e) {
    if (!$(e.target).closest("#settings-menu").length) setMenu(false);
  });
  $(document).on("keydown", function (e) {
    if (e.key === "Escape") setMenu(false);
  });

  // ---- 入力欄の高さ: 入力した行数 (折り返しも含む) に合わせて自動で伸び縮みさせる ----
  // 画面に出ていない入力欄は高さが測れないので、何もしない (表示するときに呼び直す)。
  function autoGrow(el) {
    if (!el || el.offsetParent === null) return;
    el.style.height = "auto"; // いったん縮めてから、中身の高さを測り直す
    const borders = el.offsetHeight - el.clientHeight; // 枠線の分 (border-box なので足す)
    el.style.height = el.scrollHeight + borders + "px";
    // 上限 (max-height) を超えたときだけ、スクロールバーを出す
    el.style.overflowY = el.scrollHeight > el.clientHeight + 1 ? "auto" : "hidden";
  }
  $(document).on("input", ".js-compose-text", function () {
    autoGrow(this);
  });
  $(window).on("resize", function () {
    $(".js-compose-text").each(function () { autoGrow(this); }); // 幅が変わると折り返しも変わる
  });

  // ---- 投稿モーダル ----
  const dialog = document.getElementById("compose-dialog");
  $("[data-open-compose]").on("click", function () {
    if (!dialog) return;
    dialog.showModal();
    $(dialog).find("textarea").each(function () { autoGrow(this); }).trigger("focus");
  });
  $("[data-close-compose]").on("click", function () {
    dialog.close();
  });
  $(dialog).on("click", function (e) {
    if (e.target === dialog) dialog.close(); // 外側クリックで閉じる
  });

  // ---- 文字数カウンタ (Enter+Ctrl/Cmd で送信) ----
  function updateCount($form) {
    const len = Array.from($form.find(".js-compose-text").val()).length;
    const max = Number($form.find(".js-compose-text").attr("maxlength"));
    $form.find(".js-count").text(len + "/" + max).toggleClass("text-red-600", len >= max);
  }
  $(document).on("input", ".js-compose-text", function () {
    updateCount($(this).closest("form"));
    if ($(this).attr("aria-invalid")) clearFormError($(this).closest("form"));
  });
  $(document).on("keydown", ".js-compose-text", function (e) {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      $(this).closest("form").trigger("submit");
    }
  });

  // ---- 画像の選択とプレビュー ----
  // form ごとに選んだファイルを配列で持つ (input の files は直接いじれないため)
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
      .attr("title", full ? "画像は" + MAX_IMAGES + "枚までです" : "画像を添付 (" + MAX_IMAGES + "枚まで)");
  }
  // プレビュー用の一時的な画像URL。拡大表示でも同じURLを使うので、読み込み後ではなく、
  // プレビューを作り直すとき (画像を外した・投稿した) に破棄する。
  const previewUrls = new WeakMap();
  function renderPreviews($form) {
    const files = picked.get($form[0]) || [];
    updateAddImage($form, files.length);
    (previewUrls.get($form[0]) || []).forEach(function (u) { URL.revokeObjectURL(u); });
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
        .addClass("js-zoom block cursor-zoom-in rounded-lg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-500")
        .append(
          $("<img>")
            .attr({ src: url, alt: "添付画像 " + (i + 1) })
            .addClass("size-30 rounded-lg object-cover")
        )
        .appendTo($li);
      $("<button>")
        .attr({ type: "button", "aria-label": "画像 " + (i + 1) + " を外す" })
        .addClass("absolute -right-1.5 -top-1.5 flex size-5 cursor-pointer items-center justify-center rounded-full bg-slate-700 text-xs text-white")
        .text("×")
        .on("click", function () {
          files.splice(i, 1);
          renderPreviews($form);
        })
        .appendTo($li);
      $list.append($li);
    });
  }
  $(document).on("change", ".js-compose-file", function () {
    const $form = $(this).closest("form");
    const files = picked.get($form[0]) || [];
    const incoming = Array.from(this.files);
    const room = MAX_IMAGES - files.length;
    clearFormError($form);
    if (incoming.length > room) setFormError($form, "画像は" + MAX_IMAGES + "枚までです", "images");
    files.push.apply(files, incoming.slice(0, room));
    picked.set($form[0], files);
    this.value = "";
    renderPreviews($form);
  });

  // ---- 投稿・返信の送信 ----
  // リンクの判定はサーバー (services.LINK_PATTERN) と同じ正規表現を使う
  const LINK_LIKE = new RegExp($("body").attr("data-link-pattern") || "https?://", "i");
  $(document).on("submit", ".js-compose, .js-reply-form", function (e) {
    e.preventDefault();
    const $form = $(this);
    const $submit = $form.find(".js-compose-submit");
    const text = $form.find(".js-compose-text").val();
    const files = picked.get($form[0]) || [];

    if (!text.trim() && !files.length) {
      setFormError($form, "本文を入力してください", "text");
      return;
    }
    const hasLink = LINK_LIKE.test(text);
    if (hasLink &&
        !window.confirm("本文にリンクが含まれています。リンク付きの投稿は料金が高く、1件あたり約" + $("body").data("link-price") + "かかります。投稿しますか？")) {
      return;
    }

    const data = new FormData($form[0]);
    files.forEach(function (f) { data.append("images", f); });
    if (hasLink) data.append("link_confirmed", "1"); // 確認済みの印。無いとサーバーが投稿を止める

    clearError();
    clearFormError($form);
    $submit.prop("disabled", true);
    $.ajax({
      url: $form.attr("action"),
      method: "POST",
      data: data,
      processData: false,
      contentType: false,
    })
      .done(function (res) {
        $form.find(".js-compose-text").val("").each(function () { autoGrow(this); });
        picked.delete($form[0]);
        renderPreviews($form);
        updateCount($form);
        if ($form.hasClass("js-reply-form")) {
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
  });

  // ---- 返信フォームの開閉 ----
  $(document).on("click", ".js-reply-toggle", function () {
    const $form = $(this).siblings(".js-reply-form");
    const open = $form.hasClass("hidden");
    $form.toggleClass("hidden", !open);
    $(this).attr("aria-expanded", open);
    if (open) $form.find("textarea").each(function () { autoGrow(this); }).trigger("focus");
  });

  // ---- 「ツイート取得」「リプライ取得」 ----
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
});
