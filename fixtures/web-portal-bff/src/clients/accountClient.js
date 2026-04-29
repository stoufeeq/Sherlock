import axios from 'axios';

// Account traffic is fronted by APIGEE — caller sees the gateway URL, not the
// service URL. Sherlock's api_gateway resolver unravels this into a CALLS edge
// to the real backend (account-service) with via_gateway=ubs-apigee.
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
};
