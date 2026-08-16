/**
 * MKUMBWA TRONIX - Core API Connection Module
 * Professional Centralized Service Gateway
 */

// Centralized dynamic origin endpoint calculation
const API = `${window.location.origin}/api`;

/**
 * Safe Local Storage Utility Wrapper
 */
const StorageManager = {
    setToken: (key, token) => localStorage.setItem(key, token),
    getToken: (key) => localStorage.getItem(key),
    clearAuth: () => {
        localStorage.removeItem('access_token');
        localStorage.removeItem('refresh_token');
    }
};

/**
 * Attempts to exchange the stored refresh token for a fresh access token.
 * Returns true on success, false if the refresh token is also invalid/expired.
 */
async function refreshAccessToken() {
    const refreshToken = StorageManager.getToken('refresh_token');
    if (!refreshToken) return false;

    try {
        const response = await fetch(`${window.location.origin}/api/token/refresh/`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ refresh: refreshToken })
        });

        if (!response.ok) return false;

        const data = await response.json();
        if (data && data.access) {
            StorageManager.setToken('access_token', data.access);
            return true;
        }
        return false;
    } catch (error) {
        console.error("🚨 [Token Refresh] Failed to refresh access token:", error);
        return false;
    }
}

/**
 * Same auto-refresh/retry behavior as apiRequest, but returns the raw
 * Response object instead of parsing it — use this when the caller needs
 * response.ok/status itself (e.g. file uploads with FormData).
 */
async function apiRequestRaw(endpoint, options = {}, isRetry = false) {
    const url = `${API}${endpoint}`;

    const isFormData = options.body instanceof FormData;
    options.headers = {
        ...(isFormData ? {} : { 'Content-Type': 'application/json' }),
        ...options.headers
    };

    const token = StorageManager.getToken('access_token');
    if (token) {
        options.headers['Authorization'] = `Bearer ${token}`;
    }

    const response = await fetch(url, options);

    if (response.status === 401 && !isRetry) {
        console.warn("🔒 [API Gateway] Access token rejected. Attempting silent refresh...");
        const refreshed = await refreshAccessToken();
        if (refreshed) {
            return await apiRequestRaw(endpoint, options, true);
        }
        console.warn("🔒 [API Gateway] Refresh failed. Redirecting to login.");
        StorageManager.clearAuth();
        window.location.href = '/';
        return null;
    }

    return response;
}

/**
 * Base HTTP Request Handler Engine
 */
async function apiRequest(endpoint, options = {}, isRetry = false) {
    const url = `${API}${endpoint}`;

    // Auto-inject headers (skip Content-Type for FormData — the browser sets its
    // own multipart boundary automatically, so forcing JSON here breaks file uploads)
    const isFormData = options.body instanceof FormData;
    options.headers = {
        ...(isFormData ? {} : { 'Content-Type': 'application/json' }),
        ...options.headers
    };

    // Auto-inject JWT access tokens if present
    const token = StorageManager.getToken('access_token');
    if (token) {
        options.headers['Authorization'] = `Bearer ${token}`;
    }

    try {
        const response = await fetch(url, options);

        // Handle expired/invalid access token globally: refresh once, then retry
        if (response.status === 401 && !isRetry) {
            console.warn("🔒 [API Gateway] Access token rejected. Attempting silent refresh...");
            const refreshed = await refreshAccessToken();
            if (refreshed) {
                return await apiRequest(endpoint, options, true);
            }
            // Refresh token is also dead — force re-login
            console.warn("🔒 [API Gateway] Refresh failed. Redirecting to login.");
            StorageManager.clearAuth();
            window.location.href = '/';
            return;
        }

        // If content isn't JSON, return raw text response
// If content isn't JSON, return raw text response
        const contentType = response.headers.get("content-type");
        const data = contentType && contentType.includes("application/json")
            ? await response.json()
            : await response.text();

        if (!response.ok) {
            const err = new Error("Request failed");
            err.status = response.status;
            err.data = data;
            throw err;
        }
        return data;
    } catch (error) {
        console.error(`🚨 [Network Failure] Request to ${url} dropped:`, error);
        throw error;
    }
}

/**
 * ─────────────────────────────────────────────
 * CENTRALLY EXPOSED CONTROLLERS
 * ─────────────────────────────────────────────
 */

// Authentication Operations
async function login(username, password) {
    const data = await apiRequest('/token/', {
        method: 'POST',
        body: JSON.stringify({ username, password })
    });
    if (data && data.access) {
        StorageManager.setToken('access_token', data.access);
        StorageManager.setToken('refresh_token', data.refresh);
    }
    return data;
}

async function register(userData) {
    return await apiRequest('/accounts/register/', {
        method: 'POST',
        body: JSON.stringify(userData)
    });
}

// Fetches the logged-in user's canonical profile (name, email, phone, address, photo, role)
async function fetchProfile() {
    const response = await apiRequestRaw('/accounts/profile/', { method: 'GET' });
    if (!response || !response.ok) return null;
    return await response.json();
}

// Updates the logged-in user's profile. Pass a FormData instance (supports an
// optional 'profile_photo' file field alongside the text fields) for image
// uploads, or a plain object for text-only updates.
async function updateProfile(payload) {
    const isFormData = payload instanceof FormData;
    const response = await apiRequestRaw('/accounts/profile/', {
        method: 'PATCH',
        body: isFormData ? payload : JSON.stringify(payload)
    });
    if (!response) return { ok: false, data: null };
    const data = await response.json().catch(() => null);
    return { ok: response.ok, data };
}

// Service Request Operations
async function updateRepairStatus(ticketId, newStatus, internalNote = '') {
    return await apiRequest(`/requests/${ticketId}/update_status/`, {
        method: 'POST',
        body: JSON.stringify({ status: newStatus, note: internalNote })
    });
}

async function assignTechnician(ticketId, technicianId) {
    return await apiRequest(`/requests/${ticketId}/assign_technician/`, {
        method: 'POST',
        body: JSON.stringify({ technician_id: technicianId })
    });
}

// Live Inventory Actions
async function fetchInventoryAnalytics() {
    return await apiRequest('/inventory/analytics/'); // Updated path
}

async function logPartConsumption(ticketId, sku, quantity = 1) {
    return await apiRequest('/inventory/consume/', { // Updated path
        method: 'POST',
        body: JSON.stringify({ ticket_id: ticketId, sku, quantity })
    });
}