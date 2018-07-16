CREATE TABLE `akismet_reports` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `created` datetime(6) NOT NULL,
  `modified` datetime(6) NOT NULL,
  `comment_type` varchar(255) NOT NULL,
  `user_ip` varchar(255) NOT NULL,
  `user_agent` varchar(255) NOT NULL,
  `referrer` varchar(255) NOT NULL,
  `user_name` varchar(255) NOT NULL,
  `user_email` varchar(255) NOT NULL,
  `comment` longtext NOT NULL,
  `comment_modified` datetime(6) NOT NULL,
  `content_link` varchar(255) NOT NULL,
  `content_modified` datetime(6) NOT NULL,
  `result` smallint(5) unsigned DEFAULT NULL,
  `reported` tinyint(1) NOT NULL,
  `rating_instance_id` int(11) DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `akismet_reports_rating_instance_id_d282058c_fk_reviews_id` (`rating_instance_id`),
  CONSTRAINT `akismet_reports_rating_instance_id_d282058c_fk_reviews_id` FOREIGN KEY (`rating_instance_id`) REFERENCES `reviews` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
