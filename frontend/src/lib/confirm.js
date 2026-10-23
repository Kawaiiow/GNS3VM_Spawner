export const confirmed =
    (message) =>
    ({ cancel }) => {
        if (!confirm(message)) cancel();
    };
