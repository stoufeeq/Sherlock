import axios from 'axios';

// Customer traffic is also fronted by APIGEE.
const baseURL = process.env.APIGEE_BASE_URL || 'https://api.ubs.com';
const http = axios.create({ baseURL, timeout: 2000 });

export const customerClient = {
  async get(id) {
    const { data } = await http.get(`/banking/v1/customers/${id}`);
    return data;
  },
};
