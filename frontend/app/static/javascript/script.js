function togglePassword(inputId = "password", iconId = "eye-icon") {
    let password = document.getElementById(inputId);
    let eyeIcon = document.getElementById(iconId);
    if (password.type === "password") {
        password.type = "text";
        eyeIcon.src = "/static/image/eye_close.svg";
    } else {
        password.type = "password";
        eyeIcon.src = "/static/image/eye_open.svg";
    }
}

function toggleClipboard(inputId) {
    let copyText = document.getElementById(inputId);
    navigator.clipboard.writeText(copyText.value).then(() => { copyText.blur(); })
}

document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll(".expires-at").forEach(el => {
        let d = new Date(Number(el.dataset.ts) * 1000);
        const time = d.toLocaleTimeString("en-GB", { timeZone: "Asia/Bangkok", hourCycle: "h23" });
        const date = d.toLocaleDateString("th-TH", { timeZone: "Asia/Bangkok" });
        el.textContent = `${time} - ${date}`;
    });
});
