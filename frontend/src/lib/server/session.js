import { redirect } from '@sveltejs/kit';

export const dashboardPath = (role) =>
    role === 'admin' || role === 'instructor' ? `/${role}/dashboard` : '/dashboard';

export function redirectIfSignedIn({ cookies }) {
    if (cookies.get('access_token')) redirect(303, dashboardPath(cookies.get('role')));
}
