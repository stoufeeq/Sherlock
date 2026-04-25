import axios from 'axios';

const baseURL = process.env.TRANSACTION_SERVICE_URL || 'http://transaction-service:8080';
const http = axios.create({ baseURL, timeout: 2000 });

export const transactionClient = {
  async create(body) {
    const { data } = await http.post('/transactions', body);
    return data;
  },
};
