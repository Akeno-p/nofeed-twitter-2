// ---- エラー表示 ----
const $banner = $("#error-banner");
function showError(msg, reconnect) {
  $banner.empty().append($("<span>").text(msg));
  if (reconnect) {
    $banner.append(
      $("<a>")
        .attr("href", "/x/connect/")
        .addClass("ml-2.5 underline")
        .text("連携し直す"),
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
  return [
    body.error || "通信に失敗しました。もう一度お試しください。",
    !!body.needs_reconnect,
  ];
}
