import { getJson } from '#lib/server/api.js';

export async function load(event) {
    return { user: await getJson(event, '/auth/me') };
}
