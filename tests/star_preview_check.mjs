import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';
const base = pathToFileURL(process.argv[2] + '/');
const { postPreview } = await import(new URL('post-preview.js', base));
const { activityIcon } = await import(new URL('activity-icon.js', base));
const event = { kind:'interaction.replies', post_id:'123', post_text:'😀'.repeat(150) };
const html = postPreview(event,140,'star-post');
const text = html.match(/<span>(.*?)<\/span>/)[1];
assert.equal(Array.from(text).length,140);
assert.ok(text.endsWith('…'));
assert.ok(html.includes('https://x.com/i/status/123'));
assert.equal(postPreview({...event,post_id:'javascript:alert(1)'},140,'star-post'),'');
assert.equal(postPreview({...event,kind:'follow.follow'},140,'star-post'),'');
assert.equal(postPreview({...event,post_text:'  '},140,'star-post'),'');
assert.ok(postPreview({...event,post_text:'<img onerror="bad">'},140,'star-post').includes('&lt;img'));
for (const kind of ['follow.follow','follow.unfollow','subscriptions.subscribe','subscriptions.unsubscribe',...['replies','mentions','quotes','reposts','likes_received','likes_given','your_posts'].map(k=>'interaction.'+k)]) {
 const icon=activityIcon({kind});assert.ok(icon.includes('<svg'));assert.ok(icon.includes('sr-only'));assert.ok(icon.includes('title='));
}
