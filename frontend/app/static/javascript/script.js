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
