import axios from 'axios';

const baseURL = process.env.CUSTOMER_SERVICE_URL || 'http://customer-service:8080';
const http = axios.create({ baseURL, timeout: 2000 });

export const customerClient = {
  async get(id) {
    const { data } = await http.get(`/customers/${id}`);
    return data;
  },
};
