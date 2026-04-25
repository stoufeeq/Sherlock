import axios from 'axios';

const baseURL = process.env.ACCOUNT_SERVICE_URL || 'http://account-service:8080';
const http = axios.create({ baseURL, timeout: 2000 });

export const accountClient = {
  async get(id) {
    const { data } = await http.get(`/accounts/${id}`);
    return data;
  },
  async getBalance(id) {
    const { data } = await http.get(`/accounts/${id}/balance`);
    return data;
  },
};
