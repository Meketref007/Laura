import AsyncStorage from '@react-native-async-storage/async-storage';

const STORAGE_KEYS = {
  BASE_URL: '@laura_api_base_url',
  API_KEY: '@laura_api_key',
};

const MAX_RETRIES = 2;
const RETRY_DELAY = 1000;

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function getStoredConfig() {
  const [baseUrl, apiKey] = await Promise.all([
    AsyncStorage.getItem(STORAGE_KEYS.BASE_URL),
    AsyncStorage.getItem(STORAGE_KEYS.API_KEY),
  ]);
  return {
    baseUrl: baseUrl || 'http://192.168.0.1:8888',
    apiKey: apiKey || '',
  };
}

async function request(path, options = {}, retries = MAX_RETRIES) {
  const config = await getStoredConfig();
  const url = `${config.baseUrl.replace(/\/+$/, '')}/${path.replace(/^\/+/, '')}`;

  const headers = {
    'Content-Type': 'application/json',
    ...(config.apiKey ? { 'X-API-Key': config.apiKey } : {}),
    ...options.headers,
  };

  for (let attempt = 0; attempt <= retries; attempt++) {
    try {
      const response = await fetch(url, { ...options, headers });

      if (!response.ok) {
        const text = await response.text();
        throw new Error(`HTTP ${response.status}: ${text || response.statusText}`);
      }

      const text = await response.text();
      return text ? JSON.parse(text) : null;
    } catch (error) {
      if (attempt < retries) {
        await wait(RETRY_DELAY * (attempt + 1));
        continue;
      }
      throw error;
    }
  }
}

const API = {
  async setBaseUrl(url) {
    await AsyncStorage.setItem(STORAGE_KEYS.BASE_URL, url);
  },

  async setApiKey(key) {
    await AsyncStorage.setItem(STORAGE_KEYS.API_KEY, key);
  },

  async getConfig() {
    return getStoredConfig();
  },

  async get(path) {
    return request(path, { method: 'GET' });
  },

  async post(path, data) {
    return request(path, {
      method: 'POST',
      body: data !== undefined ? JSON.stringify(data) : undefined,
    });
  },

  async testConnection() {
    const config = await getStoredConfig();
    const url = `${config.baseUrl.replace(/\/+$/, '')}/api/status`;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 5000);

    try {
      const response = await fetch(url, {
        method: 'GET',
        headers: {
          ...(config.apiKey ? { 'X-API-Key': config.apiKey } : {}),
        },
        signal: controller.signal,
      });
      clearTimeout(timeout);
      return response.ok;
    } catch {
      clearTimeout(timeout);
      return false;
    }
  },
};

export default API;
