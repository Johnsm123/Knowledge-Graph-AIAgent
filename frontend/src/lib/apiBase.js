const envBase = import.meta.env.VITE_API_BASE_URL;
export const API_HOST = envBase || "https://cognizant-care-api.azurewebsites.net";
export const API_BASE = `${API_HOST}/api/v1`;
