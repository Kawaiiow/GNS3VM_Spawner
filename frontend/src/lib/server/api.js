import { error } from '@sveltejs/kit';
import { BACKEND_URL } from '$app/env/private';

export async function api({ cookies }, path, { method = 'GET', body, timeout = 10000 } = {}) {
    try {
        return await fetch(`${BACKEND_URL}${path}`, {
            method,
            headers: {
                'content-type': 'application/json',
                cookie: `access_token=${cookies.get('access_token') ?? ''}`
            },
            body: JSON.stringify(body),
            signal: AbortSignal.timeout(timeout)
        });
    } catch (err) {
        console.error(`Backend request failed: ${BACKEND_URL}${path}`, err);
        error(503, 'Service Unavailable');
    }
}

export async function getJson(event, path) {
    const response = await api(event, path);
    if (response.status === 401 || response.status === 403) error(404, 'Not Found');
    if (!response.ok) error(500, 'Internal Error');
    return response.json();
}
