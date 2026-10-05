function togglePassword() {
    let password = document.getElementById("password");
    let eyeIcon = document.getElementById("eye-icon");
    if (password.type === "password") {
        password.type = "text";
        eyeIcon.src = "../static/image/eye_close.svg";
    } else {
        password.type = "password";
        eyeIcon.src = "../static/image/eye_open.svg";
    }
}
