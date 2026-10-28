// ---- 投稿日時: 「今」「◯分」「◯時間」を、開いたままでも更新する (_post_header.html) ----
// 判定の基準は サーバー (core_tags.time_label) と同じ。24時間以上は、サーバーが出した日付を使う。
function updateTimes() {
  const now = Date.now();
  $("time[data-reltime]").each(function () {
    const seconds = (now - Date.parse($(this).attr("datetime"))) / 1000;
    let label;
    if (seconds < 60) label = "今";
    else if (seconds < 3600) label = Math.floor(seconds / 60) + "分";
    else if (seconds < 86400) label = Math.floor(seconds / 3600) + "時間";
    else label = $(this).attr("data-abs");
    if ($(this).text() !== label) $(this).text(label);
  });
}
