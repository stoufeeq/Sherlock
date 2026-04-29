import axios from 'axios';

// Mobile-bff goes through APIGEE for account reads.
const baseURL = process.env.APIGEE_BASE_URL || 'https://api.ubs.com';
const http = axios.create({ baseURL, timeout: 2000 });

export const accountClient = {
  async get(id) {
    const { data } = await http.get(`/banking/v1/accounts/${id}`);
    return data;
  },
  async getBalance(id) {
    const { data } = await http.get(`/banking/v1/accounts/${id}/balance`);
    return data;
  },
  async getStatus(id) {
    // URL built via a const + template literal — the regex extractor sees
    // `http.get(url)` and can't recover the path; the tree-sitter JS extractor
    // walks the variable_declarator and resolves it.
    const url = `/banking/v1/accounts/${id}/status`;
    const { data } = await http.get(url);
    return data;
  },
};
