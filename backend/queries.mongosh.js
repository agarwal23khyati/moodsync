// MoodSync - sample MongoDB queries for the DBMS demo.
// Run in MongoDB Compass (MONGOSH tab at the bottom) or:  mongosh moodsync queries.mongosh.js
use("moodsync");

// 1. All collections and their document counts
db.getCollectionNames().forEach(c => print(c, db[c].countDocuments()));

// 2. Pick one user (all other queries use this id)
const u = db.users.findOne();

// 3. Open (not completed) tasks, newest first
db.tasks.find({ user_id: u._id, completed: false }).sort({ created_at: -1 });

// 4. Mood mix - aggregation ($match -> $group -> $sort)
db.mood_logs.aggregate([
  { $match: { user_id: u._id } },
  { $group: { _id: "$mood", count: { $sum: 1 } } },
  { $sort: { count: -1 } }
]);

// 5. Check-ins per day (streak data)
db.mood_logs.aggregate([
  { $match: { user_id: u._id } },
  { $group: { _id: { $dateToString: { format: "%Y-%m-%d", date: "$created_at", timezone: "Asia/Kolkata" } }, n: { $sum: 1 } } },
  { $sort: { _id: -1 } }
]);

// 6. "Join" with $lookup - every user with their task count
db.users.aggregate([
  { $lookup: { from: "tasks", localField: "_id", foreignField: "user_id", as: "t" } },
  { $project: { name: 1, email: 1, tasks: { $size: "$t" }, done: { $size: { $filter: { input: "$t", cond: "$$this.completed" } } } } }
]);

// 7. Wardrobe items per category
db.wardrobe_items.aggregate([{ $group: { _id: "$category", items: { $sum: 1 } } }]);

// 8. Prove the indexes are used (look for IXSCAN)
db.tasks.find({ user_id: u._id }).sort({ created_at: -1 }).explain("executionStats");

// 9. Indexes and schema validation rules
db.tasks.getIndexes();
db.getCollectionInfos({ name: "tasks" })[0].options.validator;

// 10. Validation in action - this insert is REJECTED (empty title, wrong types)
try { db.tasks.insertOne({ user_id: u._id, title: "", completed: "yes", created_at: new Date() }); }
catch (e) { print("Rejected by $jsonSchema:", e.codeName); }

// ---------------------------------------------------------------- agent-layer collections (added with the Coordinator/agents)
// 11. Collections now: users, mood_logs, tasks, wardrobe_items, outfits, grocery_items, recipes, recipe_rejections, tracks, song_feedback, user_preferences
// 12. Most-worn wardrobe items (worn_count feeds the Styling Agent's negative score)
db.wardrobe_items.find({ user_id: u._id }, { name: 1, category: 1, worn_count: 1 }).sort({ worn_count: -1 }).limit(5);

// 13. Outfit acceptance rate per mood: outfits -> mood_logs ($lookup join on mood_log_id)
db.outfits.aggregate([
  { $match: { user_id: u._id } },
  { $lookup: { from: "mood_logs", localField: "mood_log_id", foreignField: "_id", as: "m" } },
  { $unwind: "$m" },
  { $group: { _id: "$m.mood", shown: { $sum: 1 }, accepted: { $sum: { $cond: ["$accepted", 1, 0] } } } }
]);

// 14. Task completion rate per mood (tasks remember the mood they were created in)
db.tasks.aggregate([
  { $match: { user_id: u._id } },
  { $group: { _id: { $ifNull: ["$mood", "unspecified"] }, total: { $sum: 1 }, done: { $sum: { $cond: ["$completed", 1, 0] } } } },
  { $project: { total: 1, done: 1, ratePct: { $round: [{ $multiply: [{ $divide: ["$done", "$total"] }, 100] }, 1] } } }
]);

// 15. Referential-integrity check: outfits that point at a wardrobe item that no longer exists (must return 0)
db.outfits.aggregate([
  { $unwind: "$item_ids" },
  { $lookup: { from: "wardrobe_items", localField: "item_ids", foreignField: "_id", as: "it" } },
  { $match: { it: { $size: 0 } } },
  { $count: "orphan_references" }
]);

// 16. The user's learned preference memory (written by accept/reject feedback)
db.user_preferences.findOne({ user_id: u._id });

// 17. Recipes with their ingredient arrays (embedded) and how often each was rejected
db.recipe_rejections.aggregate([{ $group: { _id: "$recipe_id", rejected: { $sum: 1 } } }, { $sort: { rejected: -1 } }]);
