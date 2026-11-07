const {jwt: {AccessToken}} = require('twilio');
let input = '';
process.stdin.on('data', data => input += data);
process.stdin.on('end', () => {
  const p = JSON.parse(input);
  const token = new AccessToken(p.account, p.key, p.secret, {identity:p.identity, ttl:p.ttl});
  token.addGrant(new AccessToken.VoiceGrant({outgoingApplicationSid:p.app, incomingAllow:false}));
  process.stdout.write(token.toJwt());
});
