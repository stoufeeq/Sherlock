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
  async getStatus(id) {
    // URL built via a const + template literal — the regex extractor sees
    // `http.get(url)` and can't recover the path; the tree-sitter JS extractor
    // walks the variable_declarator and resolves it.
    const url = `/v2/accounts/${id}/status`;
    const { data } = await http.get(url);
    return data;
  },
};
