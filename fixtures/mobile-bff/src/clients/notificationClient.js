import axios from 'axios';

// Notifications go through APIGEE.
const baseURL = process.env.APIGEE_BASE_URL || 'https://api.ubs.com';
const http = axios.create({ baseURL, timeout: 2000 });

export const notificationClient = {
  async registerDevice(body) {
    await http.post('/banking/v1/notifications/devices', body);
  },
};
