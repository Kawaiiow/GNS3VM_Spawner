export const load = ({ cookies }) => ({
    signedIn: cookies.get('access_token') !== undefined,
    username: cookies.get('username')
});
