import { defineEnvVars } from '@sveltejs/kit/env';

export const variables = defineEnvVars({
    BACKEND_URL: { schema: (value) => value || 'http://localhost:8000' }
});
