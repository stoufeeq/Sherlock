import axios from 'axios';

const baseURL = process.env.NOTIFICATION_SERVICE_URL || 'http://notification-service:8080';
const http = axios.create({ baseURL, timeout: 2000 });

export const notificationClient = {
  async registerDevice(body) {
    await http.post('/devices', body);
  },
};
